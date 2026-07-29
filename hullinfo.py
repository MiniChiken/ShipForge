"""Measure a readable hull's vertex bounds and mesh layout."""
import struct

import granny
import grobj


def vertex_bounds(gf):
    """(count, stride, (ex, ey, ez)) for the first VertexData block."""
    tree = gf.type_tree()
    d = gf.section_data(gf.root_obj_section)
    p = gf.pointers(gf.root_obj_section)
    cur = gf.root_obj_offset
    for m in tree:
        if m["name"] == "VertexDatas":
            count = struct.unpack_from("<i", d, cur)[0]
            arr = p.get(cur + 4)
            if not arr or count < 1:
                return None
            first = gf.pointers(arr[0]).get(arr[1])
            if not first:
                return None
            vs, vo = first
            vd = gf.section_data(vs)
            vp = gf.pointers(vs)
            n = struct.unpack_from("<I", vd, vo + 8)[0]
            dp = vp.get(vo + 12)
            if not dp:
                return None
            stride = sum(grobj.member_size(x) for x in gf.type_tree(6, 0))
            buf = gf.section_data(dp[0])
            base = dp[1]
            lo = [1e30] * 3
            hi = [-1e30] * 3
            for i in range(n):
                v = struct.unpack_from("<3f", buf, base + i * stride)
                for k in range(3):
                    lo[k] = min(lo[k], v[k])
                    hi[k] = max(hi[k], v[k])
            return n, stride, tuple(hi[k] - lo[k] for k in range(3))
        cur += grobj.member_size(m)
    return None


def summarize(path_bytes):
    gf = granny.GrannyFile(path_bytes)
    r = grobj.ObjectReader(gf)
    root = r.root()
    vb = vertex_bounds(gf)
    return {
        "meshes": root["Meshes"]["count"],
        "vertices": vb[0] if vb else None,
        "stride": vb[1] if vb else None,
        "extent": vb[2] if vb else None,
    }
