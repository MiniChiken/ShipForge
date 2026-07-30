"""Extract everything ShipForge needs to know about a ship model, in one pass.

Run inside Blender because Blender is what can read the source formats and do the
raycasting:

    blender --background <model> --python blender_probe.py -- <out.json> [length]
    blender --background --python blender_probe.py -- <out.json> [length] <model>

Outputs, all in EVE space (see BASIS below):

  points        subsampled hull vertices, for the editor's three views
  bounds        measured from VERTICES, not object bounding boxes
  ellipsoid     smallest uniform inflation of the half-extents that encloses
                every vertex, origin-centred and bbox-centred
  surface       a height + normal field over the XZ plane, so the editor can snap
                a locator to the hull instantly instead of calling Blender again
  nozzles       emissive discs with radius and mean facing, so aft-facing engine
                exits can be told from vents
  anchors       silhouette extremes for navigation lights
  materials     material names, for choosing which are emissive

BASIS: centre on the bbox, scale so the longest axis is `length`, then map
Blender (x, y, z) -> EVE (x, z, -y). That is a proper -90 deg rotation about X
(determinant +1); the reflection (x, z, y) mirrors the ship, puts the exhaust at
the nose and inverts every triangle's winding.
"""
import json
import sys

import bpy
import numpy as np
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OUT = argv[0] if argv else "probe.json"
TARGET_LENGTH = float(argv[1]) if len(argv) > 1 else 1137.0
IMPORT_PATH = argv[2] if len(argv) > 2 else None

MAX_POINTS = 24000          # enough for a readable silhouette, small enough to ship
GRID_X, GRID_Z = 128, 256   # surface field resolution
EMISSIVE_HINTS = ("window", "glow", "light", "thruster", "engine glow", "lamp")


# ---------------------------------------------------------------- import ----
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
        elif lower.endswith(".dae"):
            bpy.ops.wm.collada_import(filepath=IMPORT_PATH)
        else:
            raise SystemExit("unsupported model format: %s" % IMPORT_PATH)

meshes = [o for o in bpy.data.objects if o.type == "MESH"]
if not meshes:
    raise SystemExit("no mesh objects found")


def world_vertices(o):
    n = len(o.data.vertices)
    if not n:
        return np.zeros((0, 3))
    flat = np.empty(n * 3, dtype=np.float64)
    o.data.vertices.foreach_get("co", flat)
    m = np.array(o.matrix_world)
    return flat.reshape(n, 3) @ m[:3, :3].T + m[:3, 3]


# The frame MUST come from vertices, not object bound_box corners.
#
# A rotated object's transformed local bbox overstates its extent, so a scene of
# many separate objects yields a bigger box than the same mesh joined - and the
# frame is centre-on-bbox, so the two disagree. Measured on this model: the
# joined atlas blend gave Y -125.954..+125.954 while the 25-object source blend
# gave -106.111..+145.797 from the identical 75,627 vertices. That is a pure
# 19.843m shift in Y, and it put every locator measured in one blend 19.843m
# away from geometry exported from the other. Vertices give the same answer for
# both.
_world = [world_vertices(o) for o in meshes]
_all_world = np.concatenate([w for w in _world if len(w)])
lo = Vector(_all_world.min(axis=0).tolist())
hi = Vector(_all_world.max(axis=0).tolist())
scale = TARGET_LENGTH / max(hi - lo)
centre = (lo + hi) * 0.5
print("scale x%.4f  centre %s  (frame from vertices)"
      % (scale, [round(c, 5) for c in centre]))


def to_eve_array(world):
    world = (world - np.array(centre)) * scale
    return np.stack([world[:, 0], world[:, 2], -world[:, 1]], axis=1)


def to_blender(e):
    return Vector((e[0] / scale + centre.x,
                   -e[2] / scale + centre.y,
                   e[1] / scale + centre.z))


def verts_of(o):
    n = len(o.data.vertices)
    if not n:
        return np.zeros((0, 3))
    flat = np.empty(n * 3, dtype=np.float64)
    o.data.vertices.foreach_get("co", flat)
    m = np.array(o.matrix_world)
    return to_eve_array(flat.reshape(n, 3) @ m[:3, :3].T + m[:3, 3])


# ------------------------------------------------------------- geometry ----
per_object = {o.name: verts_of(o) for o in meshes}
allv = np.concatenate([v for v in per_object.values() if len(v)])
print("vertices: %d" % len(allv))

step = max(1, len(allv) // MAX_POINTS)
points = allv[::step]

half = np.array([(allv[:, i].max() - allv[:, i].min()) * 0.5 for i in range(3)])
bbox_centre = np.array([(allv[:, i].max() + allv[:, i].min()) * 0.5 for i in range(3)])


def fit(centre_vec):
    h = np.maximum(np.abs(allv - centre_vec).max(axis=0), 1e-6)
    k = float(np.sqrt((((allv - centre_vec) / h) ** 2).sum(axis=1)).max())
    return {"centre": [round(float(c), 2) for c in centre_vec],
            "radius": [round(float(c), 2) for c in h * k],
            "inflation": round(k, 4),
            "sphere": round(float(np.sqrt(((allv - centre_vec) ** 2).sum(axis=1)).max()), 2)}


ellipsoid = {"origin": fit(np.zeros(3)), "bbox": fit(bbox_centre)}
print("ellipsoid origin-centred radius %s (inflation x%.3f)"
      % (ellipsoid["origin"]["radius"], ellipsoid["origin"]["inflation"]))

# ------------------------------------------------------- surface field ----
# A height + normal field means the editor can snap a locator to the hull, and
# tell when there is NO hull under a point, without another Blender round trip.
depsgraph = bpy.context.evaluated_depsgraph_get()
scene = bpy.context.scene
xs = np.linspace(-half[0], half[0], GRID_X)
zs = np.linspace(-half[2], half[2], GRID_Z)
top_y = float(allv[:, 1].max()) + 50.0
height = np.full((GRID_Z, GRID_X), np.nan)
normals = np.zeros((GRID_Z, GRID_X, 3))
hits = 0
for zi, z in enumerate(zs):
    for xi, x in enumerate(xs):
        hit, loc, nrm, idx, obj, mat = scene.ray_cast(
            depsgraph, to_blender([float(x), top_y, float(z)]), Vector((0.0, 0.0, -1.0)))
        if not hit:
            continue
        p = (loc - centre) * scale
        n = (mat.to_3x3() @ nrm).normalized()
        height[zi, xi] = p.z
        normals[zi, xi] = [n.x, n.z, -n.y]
        hits += 1
print("surface field: %d/%d cells hit" % (hits, GRID_X * GRID_Z))

# --------------------------------------------------------- materials ------
mat_names = sorted({s.material.name for o in meshes for s in o.material_slots
                    if s.material})


def faces_by_material(prefixes):
    out = []
    for o in meshes:
        slots = [(s.material.name if s.material else "") for s in o.material_slots]
        want = {i for i, nm in enumerate(slots)
                if any(nm.lower().startswith(p) for p in prefixes)}
        if not want:
            continue
        m3 = o.matrix_world.to_3x3()
        for poly in o.data.polygons:
            if poly.material_index in want:
                out.append((o.matrix_world @ poly.center,
                            (m3 @ poly.normal).normalized()))
    return out


def cluster(points_normals, radius):
    clusters = []
    for p, n in points_normals:
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
        pos = ((mid - centre) * scale)
        eve_n = [round(nrm.x, 3), round(nrm.z, 3), round(-nrm.y, 3)]
        out.append({"pos": [round(pos.x, 2), round(pos.z, 2), round(-pos.y, 2)],
                    "faces": c["n"],
                    # from face centres, so about 2/3 of the true disc radius
                    "radius": round(max((q - mid).length for q in c["pts"]) * scale, 2),
                    "normal": eve_n,
                    "aft": round(-eve_n[2], 3)})
    return sorted(out, key=lambda r: r["pos"][2])


emissive = [n for n in mat_names
            if any(h in n.lower() for h in EMISSIVE_HINTS)]
nozzles = cluster(faces_by_material(tuple(e.lower() for e in emissive)), 0.35) \
    if emissive else []
print("emissive materials: %s -> %d discs" % (emissive, len(nozzles)))

# ----------------------------------------------------------- anchors ------
def extreme(axis, want_max, mask=None):
    sel = allv[mask] if mask is not None else allv
    if not len(sel):
        return None
    i = int(np.argmax(sel[:, axis]) if want_max else np.argmin(sel[:, axis]))
    return [round(float(c), 2) for c in sel[i]]


stern_mask = allv[:, 2] < (allv[:, 2].min() + 25.0)
anchors = {
    "bow": extreme(2, True),
    "stern": extreme(2, False),
    "towerTop": extreme(1, True),
    "keel": extreme(1, False),
    "wingtipPort": extreme(0, False),
    "wingtipStarboard": extreme(0, True),
    "sternPort": extreme(0, False, stern_mask),
    "sternStarboard": extreme(0, True, stern_mask),
}

# -------------------------------------------------------------- write -----
out = {
    "model": IMPORT_PATH or bpy.data.filepath,
    "targetLength": TARGET_LENGTH,
    "scale": scale,
    "vertexCount": int(len(allv)),
    "bounds": {
        "min": [round(float(allv[:, i].min()), 2) for i in range(3)],
        "max": [round(float(allv[:, i].max()), 2) for i in range(3)],
        "half": [round(float(h), 2) for h in half],
        "bboxCentre": [round(float(c), 2) for c in bbox_centre],
        "meanY": round(float(allv[:, 1].mean()), 2),
    },
    "ellipsoid": ellipsoid,
    "points": [round(float(c), 1) for c in points.reshape(-1)],
    "surface": {
        "gridX": GRID_X, "gridZ": GRID_Z,
        "xs": [round(float(x), 2) for x in xs],
        "zs": [round(float(z), 2) for z in zs],
        "height": [None if np.isnan(v) else round(float(v), 2)
                   for v in height.reshape(-1)],
        "normals": [round(float(v), 3) for v in normals.reshape(-1)],
    },
    "materials": mat_names,
    "emissiveMaterials": emissive,
    "nozzles": nozzles,
    "anchors": anchors,
}
with open(OUT, "w") as fh:
    json.dump(out, fh)
print("wrote %s" % OUT)
