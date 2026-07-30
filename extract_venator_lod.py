"""Extract the Venator as ONE shape plus a LOD chain, matching EVE hull structure.

Real hulls are a single shape with 7 meshes: "<Shape>" then
"<Shape> LOD 640/320/160/80/40/20", each its own vertex data + topology.
Trinity selects among them by screen size, so a file with arbitrarily named
meshes and no LOD chain gives it nothing to pick - which is what made the
first attempt render as an invisible hull.

Run: blender --background <file>.blend --python extract_venator_lod.py -- <outdir>
"""
import json
import os
import struct
import sys

import bpy
from mathutils import Vector

OUT = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else "."
SKINNED = "--skinned" in sys.argv
TARGET_LENGTH = 1137.0
MAX_VERTS = 60000
LODS = [("", 1.00), (" LOD 640", 0.62), (" LOD 320", 0.40), (" LOD 160", 0.25),
        (" LOD 80", 0.14), (" LOD 40", 0.07), (" LOD 20", 0.035)]
SHAPE = "VenatorShape"


def half(f):
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


# --- join everything into one object -------------------------------------
bpy.ops.object.select_all(action="DESELECT")
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
for o in meshes:
    o.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]
bpy.ops.object.convert(target="MESH")      # bake geometry nodes
bpy.ops.object.join()
base = bpy.context.view_layer.objects.active
print("joined -> %s: %d verts %d polys" % (base.name, len(base.data.vertices), len(base.data.polygons)))

# --- drop the model's own sculpted turrets --------------------------------
# EVE mounts FUNCTIONAL turrets at locator_turret_* and the sculpted ones stay
# put, so the two intersect. Stock hulls model mounting plates, not guns.
#
# Selection is by MATERIAL, not object: the atlas blend is already joined into a
# single mesh, so the per-turret objects no longer exist - but material slots
# survive a join. Verified with check_turret_removal.py that this leaves the
# bounding box identical to 1e-9, so the coordinate frame (centre-on-bbox) does
# not move and every measured locator stays valid.
TURRET_MATERIALS = ("Turbolaser Barrell", "Turbolaser Body",
                    "Large Side Turbolaser")

slots = [(s.material.name if s.material else "") for s in base.material_slots]
turret_slots = {i for i, name in enumerate(slots)
                if name.startswith(TURRET_MATERIALS)}
if turret_slots:
    # bmesh, not select flags plus an operator. Setting poly.select in object
    # mode and then entering edit mode lets Blender re-derive the selection when
    # the select MODE changes, which deleted 93,616 of 134,814 faces instead of
    # the turrets' share. bmesh names the faces to remove explicitly.
    import bmesh
    mesh = base.data
    before = (len(mesh.vertices), len(mesh.polygons))
    bm = bmesh.new()
    bm.from_mesh(mesh)
    doomed = [f for f in bm.faces if f.material_index in turret_slots]
    bmesh.ops.delete(bm, geom=doomed, context="FACES")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    print("dropped sculpted turrets (%s): %d faces, %d -> %d verts, %d -> %d polys"
          % (", ".join(sorted(slots[i] for i in turret_slots)), len(doomed),
             before[0], len(mesh.vertices), before[1], len(mesh.polygons)))
else:
    print("no turret materials found - nothing dropped")

lo = Vector((1e30,) * 3)
hi = Vector((-1e30,) * 3)
for c in base.bound_box:
    w = base.matrix_world @ Vector(c)
    lo = Vector((min(lo.x, w.x), min(lo.y, w.y), min(lo.z, w.z)))
    hi = Vector((max(hi.x, w.x), max(hi.y, w.y), max(hi.z, w.z)))
scale = TARGET_LENGTH / max(hi - lo)
centre = (lo + hi) * 0.5
print("scale x%.3f" % scale)


def emit(obj, ratio):
    """Decimate a copy to `ratio` and return (vertex bytes, index bytes, counts)."""
    for m in list(obj.modifiers):
        obj.modifiers.remove(m)
    if ratio < 1.0:
        d = obj.modifiers.new("dec", "DECIMATE")
        d.ratio = ratio
    deps = bpy.context.evaluated_depsgraph_get()
    me = obj.evaluated_get(deps).to_mesh()
    me.calc_loop_triangles()
    try:
        me.calc_tangents()
        have_tan = True
    except Exception:
        have_tan = False
    uvl = me.uv_layers.active.data if me.uv_layers.active else None
    mw = obj.matrix_world
    m3 = mw.to_3x3()

    vmap = {}
    vdata = bytearray()
    tris = []
    for tri in me.loop_triangles:
        idx = []
        for li in tri.loops:
            loop = me.loops[li]
            vi = loop.vertex_index
            uv = tuple(uvl[li].uv) if uvl else (0.0, 0.0)
            tan = tuple(loop.tangent) if have_tan else (1.0, 0.0, 0.0)
            sign = loop.bitangent_sign if have_tan else 1.0
            key = (vi, round(uv[0], 4), round(uv[1], 4),
                   round(tan[0], 2), round(tan[1], 2), round(tan[2], 2))
            j = vmap.get(key)
            if j is None:
                j = len(vmap)
                vmap[key] = j
                w = mw @ me.vertices[vi].co
                p = (w - centre) * scale
                tw = (m3 @ Vector(tan)).normalized()
                # (x, z, -y) is a proper -90 deg rotation about X (det +1).
                # The earlier (x, z, y) was a REFLECTION (det -1): it mirrored
                # the ship, put the exhaust at the nose, and inverted every
                # triangle's winding.
                vdata.extend(struct.pack("<3f", p.x, p.z, -p.y))
                if SKINNED:
                    # EVE "skinned" hulls carry BoneIndices UInt8[4] and NO
                    # BoneWeights - rigid binding, not weighted skinning. All
                    # zeros binds every vertex to bone 0.
                    vdata.extend(b"\0\0\0\0")
                vdata.extend(bytes((pack_n8(tw.x), pack_n8(tw.z), pack_n8(-tw.y),
                                    pack_n8(sign))))
                vdata.extend(struct.pack("<2H", half(uv[0]), half(1.0 - uv[1])))
            idx.append(j)
        tris.append(tuple(idx))
    obj.evaluated_get(deps).to_mesh_clear()
    # indices are packed by the caller, only once the vertex count is known to
    # fit 16 bits - packing here would blow up on the very first probe
    return bytes(vdata), tris, len(vmap), len(tris)


def pack_indices32(tris):
    out = bytearray()
    for a, b, c in tris:
        out.extend(struct.pack("<3I", a, b, c))
    return bytes(out)


def pack_indices(tris):
    """Emit triangles in source winding.

    Positions use (x, z, -y), a proper rotation (det +1), so handedness is
    preserved and the source winding is already correct. The earlier reversal
    here was compensating for the old (x, z, y) REFLECTION; with a real
    rotation it inverts the faces instead of fixing them.
    """
    out = bytearray()
    for a, b, c in tris:
        out.extend(struct.pack("<3H", a, b, c))
    return bytes(out)


# 32-bit indices remove the 65535 vertex ceiling, so the base LOD ships at full
# resolution instead of being decimated to ~18% just to fit 16 bits.
ratio = 1.0
print("base at full resolution (32-bit indices)")

vbuf = bytearray()
ibuf = bytearray()
levels = []
for suffix, rel in LODS:
    v, tris, nv, nt = emit(base, min(1.0, ratio * rel))
    bits32 = nv > 65535
    levels.append({"name": SHAPE + suffix, "vertex_offset": len(vbuf),
                   "vertex_count": nv, "index_offset": len(ibuf),
                   "triangle_count": nt, "bits32": bits32})
    vbuf.extend(v)
    ibuf.extend(pack_indices32(tris) if bits32 else pack_indices(tris))
    print("    %s %s" % (SHAPE + suffix, "32-bit" if bits32 else "16-bit"))
    print("  %-24s verts=%-6d tris=%-6d" % (SHAPE + suffix, nv, nt))

with open(os.path.join(OUT, "venator_lod.bin"), "wb") as fh:
    fh.write(vbuf)
    index_base = len(vbuf)
    fh.write(ibuf)
json.dump({"scale": scale, "stride": 24 if SKINNED else 20,
           "skinned": SKINNED, "index_base": index_base,
           "shape": SHAPE, "levels": levels},
          open(os.path.join(OUT, "venator_lod.json"), "w"), indent=1)
print("levels=%d vbuf=%d ibuf=%d" % (len(levels), len(vbuf), len(ibuf)))
