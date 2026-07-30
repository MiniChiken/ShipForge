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
# The frame MUST come from VERTICES, not object bound_box corners. A rotated
# object's transformed local bbox overstates its extent, so a scene of separate
# objects yields a bigger box than the same mesh joined - and since the frame is
# centre-on-bbox, the two disagree. On this model the identical 75,627 vertices
# gave Y -125.954..+125.954 joined (venator_atlas.blend, which the .gr2 was
# exported from) against -106.111..+145.797 unjoined: a pure 19.843m shift that
# put every locator measured here that far above the hull. See compare_frames.py.
def _frame_vertices():
    chunks = []
    for o in meshes:
        n = len(o.data.vertices)
        if not n:
            continue
        flat = np.empty(n * 3, dtype=np.float64)
        o.data.vertices.foreach_get("co", flat)
        m = np.array(o.matrix_world)
        chunks.append(flat.reshape(n, 3) @ m[:3, :3].T + m[:3, 3])
    return np.concatenate(chunks)


_fv = _frame_vertices()
lo = Vector(_fv.min(axis=0).tolist())
hi = Vector(_fv.max(axis=0).tolist())
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
