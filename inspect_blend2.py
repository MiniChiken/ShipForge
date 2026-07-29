"""Second pass: world bounds, texture packing state, vertex-group usage."""
import bpy
from mathutils import Vector

meshes = [o for o in bpy.data.objects if o.type == "MESH"]

lo = Vector((1e30, 1e30, 1e30))
hi = Vector((-1e30, -1e30, -1e30))
for o in meshes:
    for c in o.bound_box:
        w = o.matrix_world @ Vector(c)
        lo = Vector((min(lo.x, w.x), min(lo.y, w.y), min(lo.z, w.z)))
        hi = Vector((max(hi.x, w.x), max(hi.y, w.y), max(hi.z, w.z)))
ext = hi - lo
print("BOUNDS lo=(%.3f, %.3f, %.3f) hi=(%.3f, %.3f, %.3f)" % (lo.x, lo.y, lo.z, hi.x, hi.y, hi.z))
print("EXTENT x=%.3f y=%.3f z=%.3f  (longest axis %.3f)" % (ext.x, ext.y, ext.z, max(ext)))
print("unit scale=%s  system=%s" % (bpy.context.scene.unit_settings.scale_length,
                                    bpy.context.scene.unit_settings.system))

packed = missing = external = 0
for img in bpy.data.images:
    if img.name == "Render Result":
        continue
    if img.packed_file is not None:
        packed += 1
    elif img.size[0] == 0:
        missing += 1
        print("  MISSING: %s -> %s" % (img.name, img.filepath))
    else:
        external += 1
print("IMAGES packed=%d external=%d missing=%d" % (packed, external, missing))

# vertex groups without an armature - are they real skinning data?
vg = {}
for o in meshes:
    for g in o.vertex_groups:
        vg[g.name] = vg.get(g.name, 0) + 1
print("VERTEX GROUP names across objects: %s" % sorted(vg))

mods = {}
for o in meshes:
    for m in o.modifiers:
        mods[m.type] = mods.get(m.type, 0) + 1
print("MODIFIERS: %s" % (mods or "none"))
