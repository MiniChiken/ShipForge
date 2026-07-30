"""Raycast the real hull surface under each turret, and audit the engine bank.

Two things the column-sampling in measure_deck.py could not answer:

  * where the DECK actually is under a turret. Sampling hull vertices in a
    +-18m column found as few as 0 of them, so "deck" came back as the belly
    ~85m below. A downward raycast onto the hull returns the true surface.
  * whether all 8 Thruster Glow discs are really main engine nozzles. They
    span 140m of Z, which is a lot for one engine bank, so this reports each
    disc against the bounds of the engine housing geometry near it.

Same basis as the rest of the pipeline: centre on bbox, scale to TARGET_LENGTH,
Blender (x,y,z) -> EVE (x, z, -y).

Run: blender --background <file>.blend --python measure_mounts.py -- <out.json>
"""
import json
import sys

import bpy
import numpy as np
from mathutils import Vector

OUT = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else "mounts.json"
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


def to_eve(v):
    p = (v - centre) * scale
    return [p.x, p.z, -p.y]


def to_blender(e):
    """Inverse of to_eve."""
    return Vector((e[0] / scale + centre.x,
                   -e[2] / scale + centre.y,
                   e[1] / scale + centre.z))


def is_turret(o):
    return o.name.startswith("Venator.") and o.name != "Venator"


depsgraph = bpy.context.evaluated_depsgraph_get()
scene = bpy.context.scene


def deck_under(eve_xz, start_y=400.0):
    """Highest hull surface below start_y at this (x, z), ignoring turrets.

    EVE +Y is up and maps to Blender +Z, so 'down' is Blender -Z. Turret hits
    are skipped by nudging the origin past them and casting again.
    """
    origin = to_blender([eve_xz[0], start_y, eve_xz[1]])
    direction = Vector((0.0, 0.0, -1.0))
    for _ in range(24):
        hit, location, normal, index, obj, matrix = scene.ray_cast(
            depsgraph, origin, direction)
        if not hit:
            return None, None
        if obj is not None and is_turret(obj.original):
            origin = location + direction * 0.001
            continue
        eve = to_eve(location)
        n = (matrix.to_3x3() @ normal).normalized()
        return eve[1], [round(n.x, 3), round(n.z, 3), round(-n.y, 3)]
    return None, None


# ---- turret mounts ------------------------------------------------------
parts = []
for o in meshes:
    if not is_turret(o):
        continue
    n = len(o.data.vertices)
    flat = np.empty(n * 3, dtype=np.float64)
    o.data.vertices.foreach_get("co", flat)
    m = np.array(o.matrix_world)
    world = flat.reshape(n, 3) @ m[:3, :3].T + m[:3, 3]
    world = (world - np.array(centre)) * scale
    v = np.stack([world[:, 0], world[:, 2], -world[:, 1]], axis=1)
    parts.append({"object": o.name, "centroid": v.mean(axis=0).tolist(),
                  "minY": float(v[:, 1].min())})

groups = {}
for p in parts:
    x, y, z = p["centroid"]
    groups.setdefault((round(z / 20.0), 1 if x > 0 else -1), []).append(p)

turrets = []
for key, members in sorted(groups.items(), key=lambda kv: (-abs(kv[0][0]), kv[0][1])):
    n = len(members)
    cx = sum(m["centroid"][0] for m in members) / n
    cz = sum(m["centroid"][2] for m in members) / n
    baseY = min(m["minY"] for m in members)
    deckY, normal = deck_under((cx, cz))
    turrets.append({"parts": [m["object"] for m in members],
                    "x": round(cx, 2), "z": round(cz, 2),
                    "baseY": round(baseY, 2),
                    "deckY": round(deckY, 2) if deckY is not None else None,
                    "deckNormal": normal})
    print("  turret x=%8.1f z=%9.1f  base=%7.2f  DECK=%s  normal=%s"
          % (cx, cz, baseY, deckY, normal))

# ---- engine bank --------------------------------------------------------
def faces_by_material(prefixes):
    """Face centres AND normals, so a nozzle can be told from a vent."""
    pts = []
    for o in meshes:
        slots = [(s.material.name if s.material else "") for s in o.material_slots]
        want = {i for i, nm in enumerate(slots) if nm.startswith(prefixes)}
        if not want:
            continue
        m3 = o.matrix_world.to_3x3()
        for poly in o.data.polygons:
            if poly.material_index in want:
                pts.append((o.matrix_world @ poly.center,
                            (m3 @ poly.normal).normalized()))
    return pts


def cluster(points, radius):
    """Group face centres into discrete discs, keeping their mean facing.

    A main engine's exhaust plane points STERNWARD (EVE -Z). Manoeuvring
    thrusters and vents share the same emissive material but face up or
    outboard, and dressing those as boosters is what put exhaust high on the
    hull, away from the engine bells.
    """
    clusters = []
    for p, n in points:
        for c in clusters:
            if (c["sum"] / c["n"] - p).length <= radius:
                c["sum"] += p
                c["pts"].append(p)
                c["nrm"] += n
                c["n"] += 1
                break
        else:
            clusters.append({"sum": p.copy(), "n": 1, "pts": [p], "nrm": n.copy()})
    out = []
    for c in clusters:
        mid = c["sum"] / c["n"]
        nrm = (c["nrm"] / c["n"]).normalized()
        eve_n = [nrm.x, nrm.z, -nrm.y]
        out.append({"pos": to_eve(mid), "faces": c["n"],
                    "radius": max((q - mid).length for q in c["pts"]) * scale,
                    "normal": [round(v, 3) for v in eve_n],
                    "aft": round(-eve_n[2], 3)})   # 1.0 = points straight astern
    return sorted(out, key=lambda r: r["pos"][2])


glow = cluster(faces_by_material(("Thruster Glow",)), 0.35)
engines = [to_eve(p) for p, _ in faces_by_material(("Engines",))]
print("\nengine housing faces: %d" % len(engines))
if engines:
    arr = np.array(engines)
    print("  Engines material Z range: %.1f .. %.1f" % (arr[:, 2].min(), arr[:, 2].max()))
    print("  Engines material Y range: %.1f .. %.1f" % (arr[:, 1].min(), arr[:, 1].max()))
print("thruster glow discs: %d" % len(glow))
for g in glow:
    print("  glow (%8.1f,%7.1f,%9.1f)  faces=%2d radius=%5.2f  normal=%-22s aft=%5.2f %s"
          % (g["pos"][0], g["pos"][1], g["pos"][2], g["faces"], g["radius"],
             g["normal"], g["aft"], "MAIN" if g["aft"] > 0.85 else "not astern"))

json.dump({"scale": scale, "turrets": turrets, "glow": glow,
           "engineZ": [float(np.array(engines)[:, 2].min()),
                       float(np.array(engines)[:, 2].max())] if engines else None},
          open(OUT, "w"), indent=1)
print("wrote %s" % OUT)
