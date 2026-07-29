"""Work out how EVE packs the 4-byte Tangent field.

The vertex format is Position | Tangent NormalUInt8[4] | TexCoord0 and carries
NO normal, so the shader must reconstruct the whole tangent frame from those 4
bytes. Getting this wrong means wrong lighting - which looks like a black hull
no matter what the albedo says.

Prior findings: decoding as (v/255)*2-1 gives xyz that is NOT unit length, the
4-vector is NOT a unit quaternion, and xyz dotted with the geometric normal is
~0 (perpendicular). That is consistent with a genuine tangent.

This computes the real UV-derived tangent from the reference hull's own
geometry and correlates it against the stored bytes. If they line up, the
encoding is a plain tangent and our writer is doing the right thing.
"""
import struct

import numpy as np

import granny
import grobj


def load(gf):
    tree = gf.type_tree()
    p = gf.pointers(gf.root_obj_section)
    cur = gf.root_obj_offset
    off = {}
    for m in tree:
        off[m["name"]] = cur
        cur += grobj.member_size(m)

    arr = p[off["VertexDatas"] + 4]
    vs, vo = gf.pointers(arr[0])[arr[1]]
    vd = gf.section_data(vs)
    vp = gf.pointers(vs)
    n = struct.unpack_from("<I", vd, vo + 8)[0]
    ds, do = vp[vo + 12]
    buf = gf.section_data(ds)
    vt = gf.type_tree(6, 0)
    stride = sum(grobj.member_size(x) for x in vt)

    pos = np.zeros((n, 3), np.float32)
    tan = np.zeros((n, 4), np.uint8)
    uv = np.zeros((n, 2), np.float32)
    # field offsets within the vertex
    fo, tof, uof = 0, None, None
    c = 0
    for m in vt:
        if m["name"] == "Tangent":
            tof = c
        if m["name"].startswith("TextureCoordinates"):
            uof = c
        c += grobj.member_size(m)
    for i in range(n):
        b = do + i * stride
        pos[i] = struct.unpack_from("<3f", buf, b)
        if tof is not None:
            tan[i] = struct.unpack_from("<4B", buf, b + tof)
        if uof is not None:
            h = struct.unpack_from("<2H", buf, b + uof)
            uv[i] = [half_to_float(h[0]), half_to_float(h[1])]

    # indices
    marr = p[off["Meshes"] + 4]
    m0 = gf.pointers(marr[0])[marr[1]]
    md = gf.section_data(m0[0])
    mp = gf.pointers(m0[0])
    MESH = [x for x in tree if x["name"] == "Meshes"][0]["children"]
    o = m0[1]
    topo = None
    for mem in MESH:
        if mem["name"] == "PrimaryTopology":
            topo = mp.get(o)
            break
        o += grobj.member_size(mem)
    td = gf.section_data(topo[0])
    tp = gf.pointers(topo[0])
    TT = [x for x in tree if x["name"] == "TriTopologies"][0]["children"]
    o = topo[1]
    idx = None
    for mem in TT:
        if mem["name"] == "Indices16":
            cnt = struct.unpack_from("<i", td, o)[0]
            ip = tp[o + 4]
            ib = gf.section_data(ip[0])
            idx = np.frombuffer(ib, "<u2", count=cnt, offset=ip[1]).astype(np.int64)
            break
        o += grobj.member_size(mem)
    return pos, tan, uv, idx.reshape(-1, 3)


def half_to_float(h):
    s = (h >> 15) & 1
    e = (h >> 10) & 0x1F
    m = h & 0x3FF
    if e == 0:
        v = (m / 1024.0) * (2.0 ** -14)
    elif e == 31:
        v = float("inf") if m == 0 else float("nan")
    else:
        v = (1.0 + m / 1024.0) * (2.0 ** (e - 15))
    return -v if s else v


def uv_tangents(pos, uv, tris):
    """Per-vertex tangent from UV derivatives, the standard construction."""
    acc = np.zeros_like(pos)
    p0, p1, p2 = pos[tris[:, 0]], pos[tris[:, 1]], pos[tris[:, 2]]
    w0, w1, w2 = uv[tris[:, 0]], uv[tris[:, 1]], uv[tris[:, 2]]
    e1, e2 = p1 - p0, p2 - p0
    d1, d2 = w1 - w0, w2 - w0
    denom = d1[:, 0] * d2[:, 1] - d2[:, 0] * d1[:, 1]
    ok = np.abs(denom) > 1e-12
    r = np.zeros_like(denom)
    r[ok] = 1.0 / denom[ok]
    t = (e1 * (d2[:, 1] * r)[:, None] - e2 * (d1[:, 1] * r)[:, None])
    for k in range(3):
        np.add.at(acc, tris[:, k], t)
    ln = np.linalg.norm(acc, axis=1, keepdims=True)
    ln[ln == 0] = 1
    return acc / ln


def main(path_bytes, label):
    gf = granny.GrannyFile(path_bytes)
    pos, tan, uv, tris = load(gf)
    ref = uv_tangents(pos, uv, tris)
    dec = (tan[:, :3].astype(np.float32) / 255.0) * 2 - 1
    ln = np.linalg.norm(dec, axis=1, keepdims=True)
    ln[ln == 0] = 1
    dec = dec / ln
    dots = (ref * dec).sum(axis=1)
    good = np.isfinite(dots)
    print("%s: n=%d" % (label, len(dots)))
    print("  dot(UV tangent, decoded xyz): mean=%.3f  |dot|>0.8: %.1f%%  |dot|>0.5: %.1f%%"
          % (dots[good].mean(), 100 * (np.abs(dots[good]) > 0.8).mean(),
             100 * (np.abs(dots[good]) > 0.5).mean()))
    w = tan[:, 3].astype(np.float32) / 255.0 * 2 - 1
    print("  4th component: mean=%.3f  frac>0: %.1f%%" % (w.mean(), 100 * (w > 0).mean()))
