"""Do two blends produce the SAME EVE coordinate frame?

The basis is centre-on-bbox then scale-to-length, so it depends entirely on the
bounding box. If the geometry was exported from one blend and the locators were
measured in another, and those blends do not have identical bounding boxes, then
every locator is offset from the hull by the difference - consistently, in one
axis, which is exactly what "the markers sit higher than the numbers say" looks
like.

    blender --background <file>.blend --python compare_frames.py -- <out.json>
"""
import json
import sys

import bpy
import numpy as np
from mathutils import Vector

OUT = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else "frame.json"
TARGET_LENGTH = 1137.0

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

chunks = []
for o in meshes:
    n = len(o.data.vertices)
    if not n:
        continue
    flat = np.empty(n * 3, dtype=np.float64)
    o.data.vertices.foreach_get("co", flat)
    m = np.array(o.matrix_world)
    world = flat.reshape(n, 3) @ m[:3, :3].T + m[:3, 3]
    world = (world - np.array(centre)) * scale
    chunks.append(np.stack([world[:, 0], world[:, 2], -world[:, 1]], axis=1))
v = np.concatenate(chunks)

info = {
    "blend": bpy.data.filepath,
    "objects": len(meshes),
    "vertices": int(len(v)),
    # the two numbers the frame is built from
    "bboxLo": [round(c, 6) for c in lo],
    "bboxHi": [round(c, 6) for c in hi],
    "blenderCentre": [round(c, 6) for c in centre],
    "scale": scale,
    # where the hull ends up in EVE space
    "eveMin": [round(float(v[:, i].min()), 3) for i in range(3)],
    "eveMax": [round(float(v[:, i].max()), 3) for i in range(3)],
    "eveMeanY": round(float(v[:, 1].mean()), 3),
}
print(json.dumps(info, indent=1))
with open(OUT, "w") as fh:
    json.dump(info, fh, indent=1)
print("wrote %s" % OUT)
