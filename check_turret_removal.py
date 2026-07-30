"""Would deleting the sculpted turrets move the coordinate frame?

The frame is centre-on-bbox of the mesh, so removing geometry can shift it - and
a shifted frame invalidates every locator that was just re-measured. The turrets
sit well inside the hull envelope (x about +-76, y about -25, z -32..-232) so they
should not touch any extreme, but that has to be checked rather than assumed.

Reports the vertex bounding box with and without the turret materials.

Run: blender --background venator_atlas.blend --python check_turret_removal.py
"""
import numpy as np

import bpy

TURRET_MATERIALS = ("Turbolaser Barrell", "Turbolaser Body",
                    "Large Side Turbolaser")

meshes = [o for o in bpy.data.objects if o.type == "MESH"]
print("objects: %d" % len(meshes))

kept = []
dropped = []
for o in meshes:
    slots = [(s.material.name if s.material else "") for s in o.material_slots]
    turret_slots = {i for i, name in enumerate(slots)
                    if name.startswith(TURRET_MATERIALS)}
    print("  %s: %d slots, %d are turret materials"
          % (o.name, len(slots), len(turret_slots)))
    for i in sorted(turret_slots):
        print("      slot %d %r" % (i, slots[i]))

    n = len(o.data.vertices)
    flat = np.empty(n * 3, dtype=np.float64)
    o.data.vertices.foreach_get("co", flat)
    m = np.array(o.matrix_world)
    world = flat.reshape(n, 3) @ m[:3, :3].T + m[:3, 3]

    # a vertex belongs to the turrets only if EVERY polygon using it does
    turret_verts = set()
    other_verts = set()
    for poly in o.data.polygons:
        target = turret_verts if poly.material_index in turret_slots else other_verts
        for vi in poly.vertices:
            target.add(vi)
    only_turret = turret_verts - other_verts
    keep_idx = [i for i in range(n) if i not in only_turret]
    kept.append(world[keep_idx])
    if only_turret:
        dropped.append(world[sorted(only_turret)])

allv = np.concatenate([w for w in kept])
print()
print("vertices kept    : %d" % len(allv))
if dropped:
    d = np.concatenate(dropped)
    print("vertices dropped : %d" % len(d))
    print("  dropped bbox lo %s" % np.round(d.min(axis=0), 4).tolist())
    print("  dropped bbox hi %s" % np.round(d.max(axis=0), 4).tolist())
else:
    print("vertices dropped : 0  (no turret materials matched!)")


def report(label, v):
    lo, hi = v.min(axis=0), v.max(axis=0)
    print("%-22s lo=%s  hi=%s  longest=%.6f"
          % (label, np.round(lo, 6).tolist(), np.round(hi, 6).tolist(),
             float((hi - lo).max())))
    return lo, hi


print()
full = np.concatenate([w for w in kept] + ([np.concatenate(dropped)] if dropped else []))
lo_full, hi_full = report("with turrets", full)
lo_keep, hi_keep = report("without turrets", allv)
print()
delta_lo = np.round(lo_keep - lo_full, 6)
delta_hi = np.round(hi_keep - hi_full, 6)
print("bbox lo shift: %s" % delta_lo.tolist())
print("bbox hi shift: %s" % delta_hi.tolist())
same = bool(np.all(np.abs(delta_lo) < 1e-9) and np.all(np.abs(delta_hi) < 1e-9))
print("FRAME UNCHANGED: %s" % same)
if not same:
    print("  -> removing the turrets WOULD move the frame; locators must be "
          "re-measured against the reduced mesh")
