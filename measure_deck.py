"""Measure where each turret actually meets the hull.

The first pass placed turret locators at each assembly's CENTROID, which sits at
mid-height of the turret model. EVE mounts its own turret graphic with the
model's pivot at the locator, so a centroid locator lifts the whole turret off
the deck by half its height - the "floating" the ship shows in space.

Two numbers per assembly, both measured rather than assumed:
  baseY - lowest point of the turret's own geometry (where it meets the hull)
  deckY - highest point of NON-turret hull geometry in the same column

Same basis as the geometry pipeline: centre on bbox, scale to TARGET_LENGTH,
Blender (x,y,z) -> EVE (x, z, -y).

Run: blender --background <file>.blend --python measure_deck.py -- <out.json>
"""
import json
import sys

import bpy
import numpy as np
from mathutils import Vector

OUT = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else "deck.json"
TARGET_LENGTH = 1137.0
COLUMN_RADIUS = 18.0   # EVE metres around a turret centre to sample the deck

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
print("scale x%.4f  centre=%s" % (scale, centre))


def verts_eve(o):
    """All of an object's vertices in EVE space as an (N,3) array."""
    n = len(o.data.vertices)
    if not n:
        return np.zeros((0, 3))
    flat = np.empty(n * 3, dtype=np.float64)
    o.data.vertices.foreach_get("co", flat)
    co = flat.reshape(n, 3)
    m = np.array(o.matrix_world)
    world = co @ m[:3, :3].T + m[:3, 3]
    world = (world - np.array(centre)) * scale
    # (x, y, z)_blender -> (x, z, -y)_eve
    return np.stack([world[:, 0], world[:, 2], -world[:, 1]], axis=1)


def is_turret(o):
    return o.name.startswith("Venator.") and o.name != "Venator"


# turret assemblies: 16 objects paired into 8 by (z row, side), as the request
# builder does, so the numbers line up with the locators actually emitted
parts = []
for o in meshes:
    if not is_turret(o):
        continue
    v = verts_eve(o)
    parts.append({"object": o.name, "centroid": v.mean(axis=0).tolist(),
                  "minY": float(v[:, 1].min()), "maxY": float(v[:, 1].max()),
                  "n": len(v)})

groups = {}
for p in parts:
    x, y, z = p["centroid"]
    groups.setdefault((round(z / 20.0), 1 if x > 0 else -1), []).append(p)

# hull geometry = everything that is not a turret
hull_parts = [verts_eve(o) for o in meshes if not is_turret(o)]
hull = np.concatenate(hull_parts) if hull_parts else np.zeros((0, 3))
print("hull verts sampled: %d   turret objects: %d" % (len(hull), len(parts)))
if not parts:
    print("NO TURRET OBJECTS - mesh names present:")
    for o in meshes[:60]:
        print("    %s" % o.name)

# Which way is up? The Venator's conning tower and dorsal fins are the only
# things that rise far off the hull, so the side with the long tail of extreme
# values is the dorsal side. If that tail is at NEGATIVE Y our vertical axis is
# inverted and every dorsal locator would be placed on the belly.
if len(hull):
    ys = hull[:, 1]
    stats = {"minY": float(ys.min()), "maxY": float(ys.max()),
             "meanY": float(ys.mean()),
             "p01": float(np.percentile(ys, 1)), "p99": float(np.percentile(ys, 99)),
             "fracAbove": float((ys > 0).mean())}
    # spread of the outermost 2% at each end - the tower end is far more extreme
    stats["upperTail"] = float(ys.max() - np.percentile(ys, 99))
    stats["lowerTail"] = float(np.percentile(ys, 1) - ys.min())
    print("hull Y: min=%.1f max=%.1f mean=%.1f p01=%.1f p99=%.1f "
          "upperTail=%.1f lowerTail=%.1f fracAbove=%.2f"
          % (stats["minY"], stats["maxY"], stats["meanY"], stats["p01"],
             stats["p99"], stats["upperTail"], stats["lowerTail"], stats["fracAbove"]))

    # True extents from VERTICES, not object bound_box corners. A rotated
    # object's transformed local bbox overstates its extent, which is how the
    # first pass ended up with a symmetric +-126 in Y for a hull that actually
    # runs -106..+146. The bounding volumes have to come from these.
    axis = {}
    for i, nm in enumerate("xyz"):
        v = hull[:, i]
        axis[nm] = {"min": float(v.min()), "max": float(v.max()),
                    "centre": float((v.min() + v.max()) * 0.5),
                    "half": float((v.max() - v.min()) * 0.5)}
        print("hull %s: min=%8.1f max=%8.1f centre=%7.1f half=%7.1f"
              % (nm.upper(), axis[nm]["min"], axis[nm]["max"],
                 axis[nm]["centre"], axis[nm]["half"]))
    stats["axis"] = axis
    c = np.array([axis[n]["centre"] for n in "xyz"])
    stats["radiusAboutCentre"] = float(np.sqrt(((hull - c) ** 2).sum(axis=1)).max())
    stats["radiusAboutOrigin"] = float(np.sqrt((hull ** 2).sum(axis=1)).max())
    print("hull enclosing radius: about centre=%.1f  about origin=%.1f"
          % (stats["radiusAboutCentre"], stats["radiusAboutOrigin"]))
else:
    stats = {}

out = []
for key, members in sorted(groups.items(), key=lambda kv: (-abs(kv[0][0]), kv[0][1])):
    n = len(members)
    cx = sum(m["centroid"][0] for m in members) / n
    cy = sum(m["centroid"][1] for m in members) / n
    cz = sum(m["centroid"][2] for m in members) / n
    baseY = min(m["minY"] for m in members)
    topY = max(m["maxY"] for m in members)

    col = hull[(np.abs(hull[:, 0] - cx) <= COLUMN_RADIUS)
               & (np.abs(hull[:, 2] - cz) <= COLUMN_RADIUS)]
    # the deck is the hull surface just under the turret, so ignore any hull
    # geometry that rises above the turret's own top (towers, fins nearby)
    below = col[col[:, 1] <= topY]
    deckY = float(below[:, 1].max()) if len(below) else None

    out.append({"parts": [m["object"] for m in members],
                "centroid": [round(cx, 2), round(cy, 2), round(cz, 2)],
                "baseY": round(baseY, 2), "topY": round(topY, 2),
                "deckY": round(deckY, 2) if deckY is not None else None,
                "columnVerts": int(len(col))})
    print("  %-28s centroid=(%8.1f,%7.1f,%9.1f) base=%7.1f top=%7.1f deck=%s (n=%d)"
          % (",".join(m["object"] for m in members), cx, cy, cz,
             baseY, topY, deckY, len(col)))

json.dump({"scale": scale, "columnRadius": COLUMN_RADIUS,
           "hullY": stats, "assemblies": out}, open(OUT, "w"), indent=1)
print("wrote %s" % OUT)
