"""Measure hull anchor points for navigation lights and spotlights.

Nav lights belong on the silhouette extremes (wingtips, bow, tower, stern) and
spotlights on the hull SURFACE aimed along its normal, so both are measured off
the model rather than guessed - the same reason the turret mounts are raycast.

Basis matches the rest of the pipeline: centre on bbox, scale to TARGET_LENGTH,
Blender (x, y, z) -> EVE (x, z, -y).

Run: blender --background <file>.blend --python measure_lights.py -- <out.json>
"""
import json
import sys

import bpy
import numpy as np
from mathutils import Vector

OUT = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else "lights.json"
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


def to_blender(e):
    return Vector((e[0] / scale + centre.x,
                   -e[2] / scale + centre.y,
                   e[1] / scale + centre.z))


def is_turret(o):
    return o.name.startswith("Venator.") and o.name != "Venator"


chunks = []
for o in meshes:
    if is_turret(o):
        continue
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
print("hull verts: %d" % len(v))

depsgraph = bpy.context.evaluated_depsgraph_get()
scene = bpy.context.scene


def surface_at(x, z, start_y=400.0):
    """Highest hull surface at (x, z), with its outward normal, ignoring turrets."""
    origin = to_blender([x, start_y, z])
    direction = Vector((0.0, 0.0, -1.0))
    for _ in range(24):
        hit, loc, nrm, idx, obj, mat = scene.ray_cast(depsgraph, origin, direction)
        if not hit:
            return None
        if obj is not None and is_turret(obj.original):
            origin = loc + direction * 0.001
            continue
        p = (loc - centre) * scale
        n = (mat.to_3x3() @ nrm).normalized()
        return {"pos": [round(p.x, 2), round(p.z, 2), round(-p.y, 2)],
                "normal": [round(n.x, 3), round(n.z, 3), round(-n.y, 3)]}
    return None


def extreme(mask, axis, want_max):
    sel = v[mask] if mask is not None else v
    if not len(sel):
        return None
    i = int(np.argmax(sel[:, axis]) if want_max else np.argmin(sel[:, axis]))
    return [round(float(c), 2) for c in sel[i]]


anchors = {}
anchors["bow"] = extreme(None, 2, True)                       # furthest +Z
anchors["towerTop"] = extreme(None, 1, True)                  # highest +Y
anchors["wingtipPort"] = extreme(None, 0, False)              # furthest -X
anchors["wingtipStarboard"] = extreme(None, 0, True)          # furthest +X
stern = v[:, 2] < (v[:, 2].min() + 25.0)
anchors["sternPort"] = extreme(stern, 0, False)
anchors["sternStarboard"] = extreme(stern, 0, True)

print("anchors:")
for k, p in anchors.items():
    print("   %-18s %s" % (k, p))

# Dorsal surface points for floodlights: along the flight-deck rims, inboard of
# the turret line so the cones fall across the deck rather than off the edge.
flood = []
for z in (180.0, 40.0, -120.0, -260.0):
    for x in (-55.0, 55.0):
        s = surface_at(x, z)
        if s:
            flood.append(s)
            print("   flood  x=%6.1f z=%7.1f -> y=%7.2f normal=%s"
                  % (x, z, s["pos"][1], s["normal"]))

json.dump({"scale": scale, "anchors": anchors, "flood": flood},
          open(OUT, "w"), indent=1)
print("wrote %s" % OUT)
