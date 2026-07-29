"""Build the authoring request for the Venator hull.

Locator positions come from locators.json, which was measured off the actual
model in the same basis as the geometry (x, z, -y; scale to 1137m), so boosters
and turrets land on the real engines and turbolasers rather than being inherited
from whatever hull was used as the template.
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NS = "res:/elysian/ships/venator"
HULL = "venator_t1"

# ab2_t1: unskinned, 2 opaque areas, quad/quadv5.fx - matches our geometry
# (stride 20, 2 trigroups, AB2_TShape1 mesh/LOD naming, AB2_T1 bone).
TEMPLATE = "res:/dx9/model/spaceobjectfactory/hulls/ab2_t1.black"
AGGREGATE = "res:/dx9/model/spaceobjectfactory/data.black"

TEXTURES = {
    "AlbedoMap":    NS + "/venator_t1_a.dds",
    "NormalMap":    NS + "/venator_t1_n.dds",
    "RoughnessMap": NS + "/venator_t1_r.dds",
    "MaterialMap":  NS + "/venator_t1_m.dds",
    "GlowMap":      NS + "/venator_t1_g.dds",
    "PaintMaskMap": NS + "/venator_t1_p3.dds",
    "DirtMap":      NS + "/venator_t1_d.dds",
}


# Booster plume length as a multiple of nozzle radius, taken from stock hulls.
PLUME_RATIO = 14.0

# A nozzle counts as a main drive if its radius is at least this fraction of the
# largest. The Venator's nozzles fall into two clear bands - 9.81/9.23 for the
# four main drives and 5.58/4.50 for the secondaries - so anything from ~0.5 to
# ~0.9 separates them; 0.7 sits in the middle of that gap.
MAIN_DRIVE_FRACTION = 0.7


def mounts_glow(here):
    """Engine nozzle discs measured by measure_mounts.py, if available."""
    path = os.path.join(here, "mounts.json")
    if not os.path.isfile(path):
        return []
    return json.load(open(path)).get("glow") or []


def main(out_dir):
    loc = json.load(open(os.path.join(HERE, "locators.json")))

    # Boosters sit on the emissive nozzle faces, sized to each nozzle's measured
    # radius rather than guessed. Polygon count is a terrible proxy for size -
    # every nozzle here is 30 faces but their radii run 4.5 to 9.8, which is why
    # the first pass produced uniformly tiny glows.
    # Boosters. Measured facts, after two wrong theories:
    #  * all 8 emissive discs face exactly astern (normal [0,0,-1]) and all sit
    #    inside the Engines housing (Z -526.8..-307.4), so none is a vent and
    #    the positions were never wrong
    #  * stock booster transforms are pure diagonal with positive Z, same as
    #    ours, so no rotation was missing either
    #
    # What was wrong: the plume LENGTH (stock runs Z:XY of about 14 - ab2 14-18,
    # gb1 13.5-14.7, mb3 10-15 - and this used 7, rendering a stubby cone that
    # reads as a flat disc), and the fact that this model's engine bank is
    # STEPPED. Four big drives sit low and aft; four smaller ones sit up to 46m
    # higher and 140m further forward. Stock ships cluster every booster at the
    # stern, so lighting the forward-upper nozzles reads as exhaust halfway up
    # the hull. Keep only the main drives.
    glow = [g for g in mounts_glow(HERE) if g.get("aft", 1.0) > 0.85]
    if glow:
        biggest = max(g["radius"] for g in glow)
        engines = [g for g in glow if g["radius"] >= MAIN_DRIVE_FRACTION * biggest]
        skipped = [g for g in glow if g not in engines]
        for g in skipped:
            print("  SKIPPED secondary nozzle pos=%s radius=%.2f"
                  % ([round(v, 1) for v in g["pos"]], g["radius"]))
    else:                                   # fall back to the older measurement
        engines = sorted(loc["engines"], key=lambda e: -e.get("radius", 0))[:4]

    boosters = []
    for e in engines:
        r = float(e.get("radius") or 4.0)
        boosters.append({"pos": [round(v, 2) for v in e["pos"]],
                         # X/Y match the nozzle opening; Z is flame length
                         "scale": [round(r, 2), round(r, 2), round(r * PLUME_RATIO, 2)],
                         "hasTrail": True,
                         "lightScale": 1.0})

    # Turrets. Three things the client's own turretSet.pyj and the stock hulls
    # settle, none of which the first pass got right:
    #
    #  * a hardpoint is the DIGITS in the name - turretSet.pyj counts sets with
    #      locatorSets = {filter(str.isdigit, loc.name) for loc in locators}
    #    so 1a and 1b are two mounting positions of ONE turret, both rendered,
    #    with only the side that has line of fire actually shooting. Four turret
    #    models therefore means two hardpoints, not four.
    #  * the locator's ROTATION is what tells the engine which way a mount faces.
    #    Every stock side turret points its local Y outboard (ab2_t1 1a is
    #    -X, 1b is +X); identity everywhere left port and starboard
    #    indistinguishable, so the wrong side fired.
    #  * EVE mounts the turret graphic pivot-at-base, so the locator belongs at
    #    the foot of the turret, not its centroid - a centroid locator lifts the
    #    gun half its own height off the deck.
    # Four hardpoints, one locator each, two per side. Distinct digit groups
    # because the client maps a fitted turret to locator_turret_<high slot + 1>
    # (TurretSet.GetSlotFromModuleFlagID), so hiSlots must equal the number of
    # groups or a turret in the last high slot has nowhere to render.
    #
    # Positions come from a downward RAYCAST onto the hull, not from the turret
    # meshes: one of the forward mounts has a hole in the hull under it (the ray
    # passes through and hits the underside 87m below), so a turret placed there
    # genuinely has nothing to stand on. Only mounts whose deck agrees with the
    # turret's own base are eligible. The mount normal is the measured surface
    # normal - about 8 degrees outboard - rather than a guessed lean.
    mounts = json.load(open(os.path.join(HERE, "mounts.json")))

    def usable(m):
        return (m["deckY"] is not None and m["deckNormal"] is not None
                and m["deckNormal"][1] > 0.5                   # surface faces up
                and abs(m["deckY"] - m["baseY"]) < 3.0)        # agrees with the turret

    # Group the 8 sculpted mounts into 4 rows of (port, starboard). Each ROW is
    # one hardpoint carrying an 'a' and a 'b' locator, which is how stock hulls
    # get "only the side facing the target fires": the client renders both and
    # picks by line of fire. 4 rows also matches hiSlots/turretSlotsLeft = 4.
    # Cutting the pairs instead of the hardpoints is what left mounts empty.
    rows = {}
    for m in mounts["turrets"]:
        rows.setdefault(round(m["z"] / 20.0), []).append(m)

    turrets = []
    # forward rows first, matching ab2_t1's fore-to-aft numbering
    for index, (_, row) in enumerate(sorted(rows.items(), reverse=True), start=1):
        port = min(row, key=lambda m: m["x"])
        starboard = max(row, key=lambda m: m["x"])
        for suffix, m, twin in (("a", port, starboard), ("b", starboard, port)):
            if usable(m):
                y, normal = m["deckY"], m["deckNormal"]
            elif usable(twin):
                # One forward mount has a hole in the hull under it, so its ray
                # falls through and reports the underside ~87m down. The ship is
                # bilaterally symmetric, so mirror the opposite mount in X
                # rather than dropping a hardpoint the player can see is empty.
                y = twin["deckY"]
                normal = [-twin["deckNormal"][0], twin["deckNormal"][1],
                          twin["deckNormal"][2]]
                print("  MIRRORED locator_turret_%d%s from its twin "
                      "(no hull under x=%s z=%s)" % (index, suffix, m["x"], m["z"]))
            else:
                y, normal = m["baseY"], [0.0, 1.0, 0.0]
                print("  FELL BACK to turret base for x=%s z=%s" % (m["x"], m["z"]))
            turrets.append({"name": "locator_turret_%d%s" % (index, suffix),
                            "pos": [m["x"], round(y, 2), m["z"]],
                            "normal": normal})

    # ---- lighting ---------------------------------------------------------
    # The Armageddon donor carries spotlightSets=0 and sprite sets pinned to ITS
    # geometry, so this hull had no light of its own anywhere. Nav lights go on
    # the measured silhouette extremes; floodlights sit on raycast deck points
    # and aim along the surface normal.
    lights = json.load(open(os.path.join(HERE, "lights.json")))
    a = lights["anchors"]
    nav_plan = [
        ("wingtipPort", 0.0),        # steady, like a port running light
        ("wingtipStarboard", 0.0),
        ("bow", 0.35),
        ("towerTop", 0.6),
        ("sternPort", 0.85),
        ("sternStarboard", 0.85),
    ]
    nav_lights = []
    for index, (name, phase) in enumerate(nav_plan):
        pos = a.get(name)
        if not pos:
            continue
        nav_lights.append({
            "name": name,
            "pos": pos,
            # stagger the phase so they do not all blink together; the wingtips
            # stay steady, which is what reads as a running light
            "blinkRate": 0.0 if phase == 0.0 else 0.2,
            "blinkPhase": phase,
            "minScale": 6.0, "maxScale": 16.0,
            "intensity": 1.0,
        })

    spotlights = []
    bow = a.get("bow")
    if bow:
        # Bow lights, mirrored either side of the centreline and aimed forward,
        # matching stock 'primary' - which sits just AHEAD of the nose.
        spotlights.append({
            "name": "primary",
            "items": [
                {"pos": [side * 9.0, bow[1], bow[2] + 6.0],
                 "direction": [0.0, 0.0, 1.0],
                 "width": 16.0, "length": 50.0,
                 "colorType": 37, "groupIndex": 2,
                 "spriteScale": [40.0, 80.0, 8.0]}
                for side in (-1.0, 1.0)
            ],
        })
    if lights.get("flood"):
        spotlights.append({
            "name": "flood",
            "items": [
                {"pos": f["pos"], "direction": f["normal"],
                 "width": 22.0, "length": 70.0,
                 "colorType": 36, "groupIndex": 0,
                 "spriteScale": [60.0, 120.0, 12.0]}
                for f in lights["flood"]
            ],
        })

    request = {
        "templateHullResource": TEMPLATE,
        "aggregateResource": AGGREGATE,
        "outputHullBlack": out_dir + "/" + HULL + ".black",
        "outputAggregateBlack": out_dir + "/data-with-venator.black",
        "scalars": {
            "name": HULL,
            "description": "ship/elysian/battleship/venator",
            "category": "battleship",
            "geometryResFilePath": NS + "/" + HULL + ".gr2",
            "isSkinned": False,
            # Fitted to the actual vertices (fit_ellipsoid.py), not eyeballed.
            # Two mistakes are corrected here. Radii equal to the half-extents
            # do NOT enclose a hull - they only touch the six face centres, and
            # this wedge tested 1.72 at (273, -126, 0), which is why the shield
            # cut through the model; the radii need a 1.23x uniform inflation
            # before every one of the 75,627 vertices is inside. And centring on
            # the bounding box put it at Y +19.8, which rides high on a hull
            # whose bulk sits at mean Y -24 (only the thin towers reach +146).
            # Centring on the origin, as stock hulls do, both looks right and
            # needs LESS inflation (1.23x against 1.32x).
            "boundingSphere": [0.0, 0.0, 0.0, 580.0],
            "shapeEllipsoidCenter": [0.0, 0.0, 0.0],
            "shapeEllipsoidRadius": [335.95, 179.34, 699.28],
        },
        "textures": TEXTURES,
        "boosters": boosters,
        "turrets": turrets,
        "navLights": nav_lights,
        "spotlights": spotlights,
    }
    path = os.path.join(HERE, "venator_request.json")
    json.dump(request, open(path, "w"), indent=1)
    print("wrote %s" % path)
    print("  boosters : %d" % len(boosters))
    for b in boosters:
        print("     pos=%-28s scale=%s" % (b["pos"], [round(v, 1) for v in b["scale"]]))
    print("  turrets  : %d" % len(turrets))
    for t in turrets:
        print("     %-22s %-26s normal=%s" % (t["name"], t["pos"], t["normal"]))
    print("  navLights: %d" % len(nav_lights))
    for n in nav_lights:
        print("     %-18s %-28s blink=%.2f phase=%.2f"
              % (n["name"], n["pos"], n["blinkRate"], n["blinkPhase"]))
    print("  spotlights: %d sets" % len(spotlights))
    for s in spotlights:
        print("     %-10s %d items" % (s["name"], len(s["items"])))
        for i in s["items"]:
            print("        pos=%-26s dir=%s" % (i["pos"], i["direction"]))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else HERE.replace("\\", "/") + "/native_out")
