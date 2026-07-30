"""Fit an axis-aligned ellipsoid that actually CONTAINS the hull.

Setting the radii to the hull's half-extents does not enclose it - that only
touches the six face centres. A flat wedge like this pokes out everywhere else:
at (273, -126, 0) the test value is (273/285)^2 + (-126-19.8)^2/140^2 = 1.72,
well outside, which is why the shield cut through the model.

Inflates the half-extent ellipsoid uniformly by the smallest factor that puts
every hull vertex inside, and reports how much of the volume that costs.

Run: blender --background <file>.blend --python fit_ellipsoid.py -- <out.json>
"""
import json
import sys

import bpy
import numpy as np
from mathutils import Vector

OUT = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else "ellipsoid.json"
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
print("vertices: %d" % len(v))

c = np.array([(v[:, i].min() + v[:, i].max()) * 0.5 for i in range(3)])
half = np.array([(v[:, i].max() - v[:, i].min()) * 0.5 for i in range(3)])
print("centre     %s" % np.round(c, 2).tolist())
print("halfExtent %s" % np.round(half, 2).tolist())

d = (v - c) / half
k = float(np.sqrt((d ** 2).sum(axis=1)).max())
radii = half * k
print("inflation needed: x%.4f  (a cuboid would need x1.7321)" % k)
print("radii      %s" % np.round(radii, 2).tolist())

# confirm: nothing outside
worst = float(np.sqrt((((v - c) / radii) ** 2).sum(axis=1)).max())
outside = int((np.sqrt((((v - c) / radii) ** 2).sum(axis=1)) > 1.0 + 1e-9).sum())
print("worst vertex test value: %.6f   vertices outside: %d" % (worst, outside))

sphere = float(np.sqrt(((v - c) ** 2).sum(axis=1)).max())
print("enclosing sphere radius about centre: %.2f" % sphere)

# The bbox centre is NOT where the ship looks like it sits. Mean Y is about -33
# because the hull is a flat wedge and only the thin conning tower and fins
# reach +146, so a volume centred on the bbox rides visibly high on the model.
# Stock hulls centre theirs on the origin (ab2_t1 is exactly [0,0,0]), so fit
# that way too and let the Y radius carry the towers.
c0 = np.zeros(3)
half0 = np.abs(v).max(axis=0)
d0 = v / half0
k0 = float(np.sqrt((d0 ** 2).sum(axis=1)).max())
radii0 = half0 * k0
outside0 = int((np.sqrt(((v / radii0) ** 2).sum(axis=1)) > 1.0 + 1e-9).sum())
sphere0 = float(np.sqrt((v ** 2).sum(axis=1)).max())
print()
print("ORIGIN-CENTRED FIT")
print("  halfExtent %s" % np.round(half0, 2).tolist())
print("  inflation  x%.4f" % k0)
print("  radii      %s" % np.round(radii0, 2).tolist())
print("  vertices outside: %d   enclosing sphere: %.2f" % (outside0, sphere0))
print("  mean Y %.1f (hull bulk sits below the bbox centre)" % v[:, 1].mean())

json.dump({"centre": [round(x, 2) for x in c.tolist()],
           "halfExtent": [round(x, 2) for x in half.tolist()],
           "inflation": round(k, 4),
           "radii": [round(x, 2) for x in radii.tolist()],
           "sphereRadius": round(sphere, 2),
           "verticesOutside": outside,
           "originCentred": {
               "centre": [0.0, 0.0, 0.0],
               "halfExtent": [round(x, 2) for x in half0.tolist()],
               "inflation": round(k0, 4),
               "radii": [round(x, 2) for x in radii0.tolist()],
               "sphereRadius": round(sphere0, 2),
               "verticesOutside": outside0,
           }}, open(OUT, "w"), indent=1)
print("wrote %s" % OUT)
