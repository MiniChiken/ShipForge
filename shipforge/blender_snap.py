"""Exact surface raycast for a handful of points.

The probe's height field is a grid (~4m cells here), which is fine for instant
feedback but wrong to snap with: on a stepped hull the nearest cell can land on
a deck several metres above the pocket the locator actually sits in. Measured
against this model, grid samples disagreed with an exact raycast at the same
coordinates by 4 to 9 metres.

So snapping raycasts the real geometry at the real coordinates.

    blender --background <model> --python blender_snap.py -- <request.json> <result.json>
    blender --background --python blender_snap.py -- <request.json> <result.json> <model>

request: {"targetLength": 1137.0, "points": [[x, z], ...],
          "ignoreNamePrefix": "Venator."}
"""
import json
import sys

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
REQUEST, RESULT = argv[0], argv[1]
IMPORT_PATH = argv[2] if len(argv) > 2 else None

req = json.loads(open(REQUEST).read())
TARGET_LENGTH = float(req.get("targetLength") or 1137.0)
IGNORE = req.get("ignoreNamePrefix") or ""

if IMPORT_PATH:
    lower = IMPORT_PATH.lower()
    if lower.endswith(".blend"):
        bpy.ops.wm.open_mainfile(filepath=IMPORT_PATH)
    else:
        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        if lower.endswith(".obj"):
            bpy.ops.wm.obj_import(filepath=IMPORT_PATH)
        elif lower.endswith((".glb", ".gltf")):
            bpy.ops.import_scene.gltf(filepath=IMPORT_PATH)
        elif lower.endswith(".fbx"):
            bpy.ops.import_scene.fbx(filepath=IMPORT_PATH)
        elif lower.endswith(".stl"):
            bpy.ops.wm.stl_import(filepath=IMPORT_PATH)

meshes = [o for o in bpy.data.objects if o.type == "MESH"]
lo = Vector((1e30,) * 3)
hi = Vector((-1e30,) * 3)
for o in meshes:
    for c in o.bound_box:
        w = o.matrix_world @ Vector(c)
        lo = Vector((min(lo.x, w.x), min(lo.y, w.y), min(lo.z, w.z)))
        hi = Vector((max(hi.x, w.x), max(hi.y, w.y), max(hi.z, w.z)))
scale = TARGET_LENGTH / max(hi - lo)
centre = (lo + hi) * 0.5


def to_blender(e):
    return Vector((e[0] / scale + centre.x,
                   -e[2] / scale + centre.y,
                   e[1] / scale + centre.z))


def ignored(obj):
    return bool(IGNORE) and obj.name.startswith(IGNORE) and obj.name != IGNORE.rstrip(".")


depsgraph = bpy.context.evaluated_depsgraph_get()
scene = bpy.context.scene
start_y = (hi.z - centre.z) * scale + 100.0

out = []
for x, z in req["points"]:
    origin = to_blender([float(x), start_y, float(z)])
    direction = Vector((0.0, 0.0, -1.0))
    hit_info = None
    for _ in range(32):
        hit, loc, nrm, idx, obj, mat = scene.ray_cast(depsgraph, origin, direction)
        if not hit:
            break
        if obj is not None and ignored(obj.original):
            origin = loc + direction * 0.001
            continue
        p = (loc - centre) * scale
        n = (mat.to_3x3() @ nrm).normalized()
        hit_info = {"y": round(p.z, 3),
                    "normal": [round(n.x, 4), round(n.z, 4), round(-n.y, 4)],
                    "object": obj.name}
        break
    out.append({"x": x, "z": z, "hit": hit_info})
    print("  (%8.2f, %9.2f) -> %s" % (x, z, hit_info))

json.dump({"success": True, "scale": scale, "results": out}, open(RESULT, "w"))
print("wrote %s" % RESULT)
