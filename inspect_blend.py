"""Report what's actually inside the Venator .blend.

Run: blender --background <file>.blend --python inspect_blend.py
"""
import bpy

scene = bpy.context.scene
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]

print("=" * 60)
print("OBJECTS: %d total, %d mesh, %d armature" % (len(bpy.data.objects), len(meshes), len(arms)))

total_v = total_t = 0
for o in meshes:
    m = o.data
    tris = sum(len(p.vertices) - 2 for p in m.polygons)
    total_v += len(m.vertices)
    total_t += tris
    groups = len(o.vertex_groups)
    uvs = [uv.name for uv in m.uv_layers]
    print("  %-34s v=%-7d tris=%-7d mats=%-2d uv=%s vgroups=%d"
          % (o.name[:34], len(m.vertices), tris, len(o.material_slots), uvs, groups))

print("-" * 60)
print("TOTAL vertices=%d triangles=%d" % (total_v, total_t))

print("MATERIALS: %d" % len(bpy.data.materials))
for mat in bpy.data.materials:
    print("  %s" % mat.name)

print("IMAGES referenced: %d" % len(bpy.data.images))
for img in bpy.data.images:
    if img.name != "Render Result":
        print("  %-50s %s %s" % (img.name[:50], tuple(img.size), img.filepath[:60]))

# world-space bounds, for scaling against EVE hull dimensions later
if meshes:
    xs = ys = zs = None
    for o in meshes:
        for c in o.bound_box:
            w = o.matrix_world @ __import__("mathutils").Vector(c)
            xs = (min(xs[0], w.x), max(xs[1], w.x)) if xs else (w.x, w.x)
            ys = (min(ys[0], w.y), max(ys[1], w.y)) if ys else (w.y, w.y)
            zs = (min(zs[0], w.z), max(zs[1], w.z)) if zs else (w.z, w.z)
    print("-" * 60)
    print("WORLD BOUNDS x=%.3f..%.3f  y=%.3f..%.3f  z=%.3f..%.3f" % (xs + ys + zs))
    print("EXTENT      x=%.3f y=%.3f z=%.3f" % (xs[1] - xs[0], ys[1] - ys[0], zs[1] - zs[0]))
print("scene unit scale: %s" % scene.unit_settings.scale_length)
print("=" * 60)
