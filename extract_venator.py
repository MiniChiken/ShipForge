"""Extract Venator geometry from the .blend into a gr2-ready intermediate.

Run: blender --background <file>.blend --python extract_venator.py -- <outdir>

Emits venator_mesh.bin (vertex + index buffers) and venator_mesh.json.

Conventions derived from real EVE hulls:
  * 1 model unit ~= 1 metre (measured across 8 battleships, ratio 0.85-1.11;
    ArtToolInfo.UnitsPerMeter=100 is vestigial Maya metadata, not world scale)
  * length runs along +Z; Blender's length axis is +Y, so axes are swapped
  * vertex = Position Real32[3] | Tangent NormalUInt8[4] | TexCoord Real16[2]
  * indices are 16-bit, so every chunk must stay under 65536 vertices
"""
import json
import os
import struct
import sys

import bpy
from mathutils import Vector

OUT = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else "."
TARGET_LENGTH = 1137.0   # canonical Venator length in metres
MAX_VERTS = 60000        # headroom under the 65535 16-bit index ceiling


def half(f):
    """float32 -> IEEE 754 binary16 bits."""
    b = struct.unpack("<I", struct.pack("<f", f))[0]
    s = (b >> 16) & 0x8000
    e = ((b >> 23) & 0xFF) - 112
    m = b & 0x7FFFFF
    if e <= 0:
        return s
    if e >= 0x1F:
        return s | 0x7C00
    return s | (e << 10) | (m >> 13)


def pack_n8(v):
    return max(0, min(255, int(round((v * 0.5 + 0.5) * 255.0))))


deps = bpy.context.evaluated_depsgraph_get()
meshes = [o for o in bpy.data.objects if o.type == "MESH"]

# world bounds -> uniform scale to canonical length
lo = Vector((1e30,) * 3)
hi = Vector((-1e30,) * 3)
for o in meshes:
    for c in o.bound_box:
        w = o.matrix_world @ Vector(c)
        lo = Vector((min(lo.x, w.x), min(lo.y, w.y), min(lo.z, w.z)))
        hi = Vector((max(hi.x, w.x), max(hi.y, w.y), max(hi.z, w.z)))
scale = TARGET_LENGTH / max(hi - lo)
centre = (lo + hi) * 0.5
print("source extent %.3f  scale x%.3f" % (max(hi - lo), scale))

materials = []
chunks = []
vbuf = bytearray()
ibuf = bytearray()

cur_verts = {}      # (vidx, uvkey, tkey) -> local index
cur_vdata = bytearray()
cur_tris = []       # (mat_index, (a,b,c))


def flush(name):
    global cur_verts, cur_vdata, cur_tris
    if not cur_tris:
        return
    cur_tris.sort(key=lambda t: t[0])
    groups = []
    order = []
    first = 0
    last_mat = None
    for mat, tri in cur_tris:
        if mat != last_mat:
            if last_mat is not None:
                groups.append({"MaterialIndex": last_mat, "TriFirst": first,
                               "TriCount": len(order) - first})
            first = len(order)
            last_mat = mat
        order.append(tri)
    groups.append({"MaterialIndex": last_mat, "TriFirst": first,
                   "TriCount": len(order) - first})
    ioff = len(ibuf)
    for a, b, c in order:
        ibuf.extend(struct.pack("<3H", a, b, c))
    chunks.append({
        "name": name,
        "vertex_offset": len(vbuf), "vertex_count": len(cur_verts),
        "index_offset": ioff, "triangle_count": len(order),
        "groups": groups,
    })
    vbuf.extend(cur_vdata)
    cur_verts = {}
    cur_vdata = bytearray()
    cur_tris = []


chunk_id = 0
for o in meshes:
    ev = o.evaluated_get(deps)
    me = ev.to_mesh()
    me.calc_loop_triangles()
    try:
        me.calc_tangents()
        have_tan = True
    except Exception:
        have_tan = False
    uvl = me.uv_layers.active.data if me.uv_layers.active else None
    mw = o.matrix_world

    slot_names = [(s.material.name if s.material else "None") for s in o.material_slots] or ["None"]
    slot_map = []
    for nm in slot_names:
        if nm not in materials:
            materials.append(nm)
        slot_map.append(materials.index(nm))

    for tri in me.loop_triangles:
        if len(cur_verts) + 3 > MAX_VERTS:
            flush("VenatorShape_%02d" % chunk_id)
            chunk_id += 1
        idx = []
        for li in tri.loops:
            loop = me.loops[li]
            vi = loop.vertex_index
            uv = tuple(uvl[li].uv) if uvl else (0.0, 0.0)
            tan = tuple(loop.tangent) if have_tan else (1.0, 0.0, 0.0)
            sign = loop.bitangent_sign if have_tan else 1.0
            key = (vi, round(uv[0], 5), round(uv[1], 5),
                   round(tan[0], 3), round(tan[1], 3), round(tan[2], 3))
            j = cur_verts.get(key)
            if j is None:
                j = len(cur_verts)
                cur_verts[key] = j
                w = mw @ me.vertices[vi].co
                p = (w - centre) * scale
                tw = (mw.to_3x3() @ Vector(tan)).normalized()
                # Blender Y is length, EVE Z is length
                cur_vdata.extend(struct.pack("<3f", p.x, p.z, p.y))
                cur_vdata.extend(bytes((pack_n8(tw.x), pack_n8(tw.z), pack_n8(tw.y),
                                        pack_n8(sign))))
                cur_vdata.extend(struct.pack("<2H", half(uv[0]), half(1.0 - uv[1])))
            idx.append(j)
        mat = slot_map[tri.material_index] if tri.material_index < len(slot_map) else 0
        cur_tris.append((mat, tuple(idx)))
    ev.to_mesh_clear()

flush("VenatorShape_%02d" % chunk_id)

with open(os.path.join(OUT, "venator_mesh.bin"), "wb") as fh:
    fh.write(vbuf)
    index_base = len(vbuf)
    fh.write(ibuf)

manifest = {
    "scale": scale, "target_length": TARGET_LENGTH,
    "stride": 20, "index_base": index_base,
    "materials": materials, "chunks": chunks,
}
with open(os.path.join(OUT, "venator_mesh.json"), "w") as fh:
    json.dump(manifest, fh, indent=1)

print("chunks=%d materials=%d vbuf=%d ibuf=%d"
      % (len(chunks), len(materials), len(vbuf), len(ibuf)))
for c in chunks:
    print("  %-20s verts=%-6d tris=%-6d groups=%d"
          % (c["name"], c["vertex_count"], c["triangle_count"], len(c["groups"])))
