"""Seed a ShipForge project from the existing hand-built Venator configuration.

Reads the current authoring request and localization request in the venator
tooling directory so the numbers come from what is actually deployed, rather
than being retyped.

    python seed_venator.py
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
PROJECTS = HERE / "projects"
PROJECTS.mkdir(exist_ok=True)

request = json.loads((TOOLS / "venator_request.json").read_text("utf-8"))
scalars = request["scalars"]

# Every resource that an FSD rollback would revert, so Deploy republishes them.
extra = []
for suffix in ("a", "n", "r", "m", "g", "p3", "d"):
    local = TOOLS / ("venator_%s.dds" % suffix)
    if local.is_file():
        extra.append(["res:/elysian/ships/venator/venator_t1_%s.dds" % suffix,
                      str(local)])
for icon in sorted((TOOLS / "icons").glob("900001_*")):
    extra.append(["res:/elysian/ships/venator/icons/" + icon.name, str(icon)])
loc_request = TOOLS / "loc_request.json"
if loc_request.is_file():
    for entry in json.loads(loc_request.read_text("utf-8"))["files"]:
        if Path(entry["output"]).is_file():
            extra.append([entry["logical"], entry["output"]])

ellipsoid_centre = list(scalars["shapeEllipsoidCenter"])
project = {
    "name": "venator",
    "hullName": "venator_t1",
    "templateHull": request["templateHullResource"],
    "resourceNamespace": "res:/elysian/ships/venator",
    "category": scalars.get("category", "battleship"),
    "sofDescription": scalars.get("description"),
    "targetLength": 1137.0,
    "model": str(TOOLS / "source" / "source" /
                 "Sketchfab_2021_06_02_08_56_33.blend"),
    # turret meshes are separate objects and must not block a surface raycast
    "ignoreNamePrefix": "Venator.",
    # SOF DNA for the Trinity viewer, and the faction whose material set the _m
    # map was tuned against (amarrbase band 1 = white_ivory_matt)
    "typeID": 900001,
    "sofFaction": "amarrbase",
    "sofRace": "amarr",
    "shield": {
        "centre": ellipsoid_centre,
        "radius": list(scalars["shapeEllipsoidRadius"]),
        "sphere": scalars["boundingSphere"][3],
        # measured half-extents, so the validator can catch a shield smaller
        # than the hull
        "halfExtent": [273.12, 125.95, 568.5],
    },
    "turrets": request.get("turrets", []),
    "boosters": request.get("boosters", []),
    "navLights": request.get("navLights", []),
    "spotlights": request.get("spotlights", []),
    "textures": request.get("textures", {}),
    # 4 turret locator GROUPS (1a/1b .. 4a/4b), so hiSlots must be 4
    "dogma": {"hiSlots": 4, "turretSlotsLeft": 4, "medSlots": 8, "lowSlots": 4},
    "serverContainer": "evejs-fresh-server-1",
    "extraResources": extra,
}

out = PROJECTS / "venator.json"
out.write_text(json.dumps(project, indent=1), "utf-8")
print("wrote %s" % out)
print("  turrets %d  boosters %d  navLights %d  spotlight sets %d"
      % (len(project["turrets"]), len(project["boosters"]),
         len(project["navLights"]), len(project["spotlights"])))
print("  extra resources to republish after an FSD rollback: %d" % len(extra))
