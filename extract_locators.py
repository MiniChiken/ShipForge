"""Derive booster and turret locator positions from the Venator's own geometry.

Native authoring means locators no longer have to be inherited from a borrowed
hull - they can sit on this model's actual engines and turrets.

Object names do not map to function in this model (only 4 "MidThruster" objects
exist, and no object is named for a turret), so selection is by MATERIAL, with
spatial clustering to separate individual nozzles. The 16 "Venator.NNN" objects
are the turbolaser turrets.

Positions must use the SAME basis as the geometry pipeline:
  centre on the model bbox, scale to TARGET_LENGTH,
  Blender (x,y,z) -> EVE (x, z, -y)   (proper rotation, det +1)

Run: blender --background <file>.blend --python extract_locators.py -- <out.json>
"""
import json
import sys

import bpy
from mathutils import Vector

OUT = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else "locators.json"
TARGET_LENGTH = 1137.0

# ONLY the emissive nozzle face. Including "Engines" (17,584 polys of housing and
# engine folds) drags each centroid off the nozzle opening and onto the engine
# body, which is why the first pass put small glows beside the nozzles.
ENGINE_MATERIALS = ("Thruster Glow",)
TURRET_MATERIALS = ("Turbolaser Barrell", "Turbolaser Body", "Large Side Turbolaser")

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
print("scale x%.3f" % scale)


def to_eve(v):
    p = (v - centre) * scale
    return [p.x, p.z, -p.y]


def faces_by_material(name_prefixes):
    """World-space face centroids whose material name starts with a prefix."""
    pts = []
    for o in meshes:
        slots = [(s.material.name if s.material else "") for s in o.material_slots]
        want = {i for i, n in enumerate(slots) if n.startswith(name_prefixes)}
        if not want:
            continue
        me = o.data
        for poly in me.polygons:
            if poly.material_index in want:
                pts.append(o.matrix_world @ poly.center)
    return pts


def cluster(points, radius):
    """Cheap greedy spatial clustering - enough to separate discrete nozzles."""
    clusters = []
    for p in points:
        placed = False
        for c in clusters:
            if (c["sum"] / c["n"] - p).length <= radius:
                c["sum"] += p
                c["pts"].append(p)
                c["n"] += 1
                placed = True
                break
        if not placed:
            clusters.append({"sum": p.copy(), "n": 1, "pts": [p]})
    out = []
    for c in clusters:
        centre = c["sum"] / c["n"]
        # nozzle radius in EVE units, so the flame can be sized to the opening
        # instead of guessed from polygon count
        spread = max((q - centre).length for q in c["pts"]) * scale
        # rearmost point of the nozzle - the flame should start at the exit plane
        back = min(to_eve(q)[2] for q in c["pts"])
        out.append({"pos": to_eve(centre), "faces": c["n"],
                    "radius": spread, "backZ": back})
    out.sort(key=lambda r: -r["faces"])
    return out


eng_pts = faces_by_material(ENGINE_MATERIALS)
engines = [c for c in cluster(eng_pts, 0.35) if c["faces"] >= 20]
print("engine faces=%d -> %d clusters" % (len(eng_pts), len(engines)))
for e in engines[:16]:
    print("   engine  (%8.1f, %8.1f, %8.1f)  faces=%d"
          % (e["pos"][0], e["pos"][1], e["pos"][2], e["faces"]))

# turrets: the repeated Venator.NNN objects
turrets = []
for o in meshes:
    if o.name == "Venator" or not o.name.startswith("Venator."):
        continue
    acc = Vector((0.0, 0.0, 0.0))
    for v in o.data.vertices:
        acc += o.matrix_world @ v.co
    turrets.append({"object": o.name, "pos": to_eve(acc / max(1, len(o.data.vertices))),
                    "verts": len(o.data.vertices)})
turrets.sort(key=lambda r: -r["pos"][2])
print("turret objects: %d" % len(turrets))
for t in turrets:
    print("   %-14s (%8.1f, %8.1f, %8.1f)  v=%d"
          % (t["object"], t["pos"][0], t["pos"][1], t["pos"][2], t["verts"]))

json.dump({"scale": scale, "target_length": TARGET_LENGTH,
           "engines": engines, "turrets": turrets}, open(OUT, "w"), indent=1)
print("wrote %s" % OUT)
