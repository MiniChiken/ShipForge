"""Verify triangle winding produces outward-facing normals.

The user reported transparent sides, which is backface culling: writing
positions as (x, z, y) is an odd axis permutation, so it mirrors the space and
flips every triangle's winding. This checks the result without needing the
client - for a mostly convex hull, a correctly wound triangle's geometric
normal should point away from the model centroid.
"""
import struct
import sys

import numpy as np

import granny
import grobj


def check(path, sample=20000):
    g = granny.GrannyFile(open(path, "rb").read())
    r = grobj.ObjectReader(g)
    root = r.root()
    mesh = root["Meshes"]["items"][0]

    # vertex positions
    tree = g.type_tree()
    d = g.section_data(g.root_obj_section)
    p = g.pointers(g.root_obj_section)
    cur = g.root_obj_offset
    vd_off = None
    for m in tree:
        if m["name"] == "VertexDatas":
            arr = p[cur + 4]
            vd_off = g.pointers(arr[0])[arr[1]]
            break
        cur += grobj.member_size(m)
    vs, vo = vd_off
    vdd = g.section_data(vs)
    vp = g.pointers(vs)
    n = struct.unpack_from("<I", vdd, vo + 8)[0]
    ds, do = vp[vo + 12]
    buf = g.section_data(ds)
    stride = sum(grobj.member_size(x) for x in g.type_tree(6, 0))
    pos = np.array([struct.unpack_from("<3f", buf, do + i * stride) for i in range(n)])

    idx = mesh["PrimaryTopology"]["Indices16"]
    # re-read indices raw
    tt = [m for m in tree if m["name"] == "TriTopologies"][0]
    arr2 = p[[o for o in [0]][0] + 0] if False else None
    # simpler: pull from the mesh's own topology pointer
    tsec, toff = None, None
    # locate via Meshes array -> first mesh -> PrimaryTopology
    # fall back: scan for the Indices16 buffer we know the size of
    count = idx["count"]

    # walk mesh struct to find its topology pointer
    marr = None
    cur = g.root_obj_offset
    for m in tree:
        if m["name"] == "Meshes":
            marr = p[cur + 4]
            break
        cur += grobj.member_size(m)
    mp = g.pointers(marr[0])
    m0 = mp[marr[1]]
    msec, moff = m0
    md = g.section_data(msec)
    mptrs = g.pointers(msec)
    MESH = [x for x in tree if x["name"] == "Meshes"][0]["children"]
    off = moff
    topo = None
    for mem in MESH:
        if mem["name"] == "PrimaryTopology":
            topo = mptrs.get(off)
            break
        off += grobj.member_size(mem)
    tsec, toff = topo
    td = g.section_data(tsec)
    tp = g.pointers(tsec)
    TT = [x for x in tree if x["name"] == "TriTopologies"][0]["children"]
    off = toff
    indices = None
    for mem in TT:
        if mem["name"] == "Indices16":
            c = struct.unpack_from("<i", td, off)[0]
            ip = tp[off + 4]
            ib = g.section_data(ip[0])
            indices = np.frombuffer(ib, dtype="<u2", count=c, offset=ip[1])
            break
        off += grobj.member_size(mem)

    tris = indices.reshape(-1, 3).astype(np.int64)
    centroid = pos.mean(axis=0)
    step = max(1, len(tris) // sample)
    t = tris[::step]
    a, b, c = pos[t[:, 0]], pos[t[:, 1]], pos[t[:, 2]]
    nrm = np.cross(b - a, c - a)
    face_c = (a + b + c) / 3.0
    outward = face_c - centroid
    ln = np.linalg.norm(nrm, axis=1) * np.linalg.norm(outward, axis=1)
    ok = ln > 1e-9
    dots = (nrm[ok] * outward[ok]).sum(axis=1) / ln[ok]
    frac = float((dots > 0).mean())
    print("%s" % path)
    print("  triangles=%d sampled=%d" % (len(tris), len(dots)))
    print("  outward-facing fraction = %.1f%%  (mean dot %.3f)" % (100 * frac, dots.mean()))
    return frac


if __name__ == "__main__":
    for pth in sys.argv[1:]:
        check(pth)
