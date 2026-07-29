"""Add the Venator as a server-side ship type + dogma record.

The running server is the C:\\evejs-fresh install (verified from the container's
compose working_dir), and its static tables live in the gamestore volume at
/var/lib/evejs/gameStore/data/<table>/data.json.

Everything here is ADDITIVE - a new typeID 900001 is appended, nothing existing
is edited. Originals are copied to *.venator-backup inside the container first.

    python server_patch.py apply
    python server_patch.py revert
"""
import json
import subprocess
import sys

CONTAINER = "evejs-fresh-server-1"
BASE = "/var/lib/evejs/gameStore/data"
# itemTypes is what the GM /item command resolves against
# (itemTypeRegistry.js -> readStaticRows(TABLE.ITEM_TYPES)); shipTypes alone is
# not enough to spawn one.
TABLES = ("shipTypes", "itemTypes", "typeDogma")

TYPE_ID = 900001
GRAPHIC_ID = 900001
# Maelstrom, matching the client-side FSD donor in fsd_insert.py. It is the
# Minmatar battleship whose bonuses are projectile damage + shield boost, so
# cloning it is what makes the ship a shield-tanked gunship on BOTH sides of
# the wire. Client and server must agree or the fitting window and the server's
# dogma disagree about the same hull.
TEMPLATE = 24694          # Maelstrom
NAME = "Venator"

# dogma attribute IDs
FIGHTER_TUBES = 2216
FIGHTER_CAPACITY = 2055

# Same layout and tank as the client's typedogma patch - see fsd_insert.py.
ATTRIBUTES = {
    14: 4,          # hiSlots - must match the hull's turret locator groups
    102: 4,         # turretSlotsLeft
    101: 0,         # launcherSlotsLeft
    13: 8,          # medSlots
    12: 4,          # lowSlots
    263: 15000,     # shieldCapacity
    265: 5500,      # armorHP
    9: 9000,        # structure hp
    271: 0.75,      # shieldEmResonance
    272: 0.4,       # shieldExplosiveResonance
    273: 0.5,       # shieldKineticResonance
    274: 0.65,      # shieldThermalResonance
    479: 1800000,   # shieldRechargeRate
    552: 500,       # signatureRadius
    FIGHTER_TUBES: 3,
    FIGHTER_CAPACITY: 3000,
}


def sh(*args):
    return subprocess.run(args, capture_output=True, text=True)


def docker(*args):
    return sh("docker", "exec", CONTAINER, "sh", "-c", " ".join(args))


def path(table):
    return "%s/%s/data.json" % (BASE, table)


def pull(table, local):
    r = sh("docker", "cp", "%s:%s" % (CONTAINER, path(table)), local)
    if r.returncode:
        raise SystemExit("docker cp failed for %s: %s" % (table, r.stderr))


def push(local, table):
    r = sh("docker", "cp", local, "%s:%s" % (CONTAINER, path(table)))
    if r.returncode:
        raise SystemExit("docker cp back failed for %s: %s" % (table, r.stderr))


def backup():
    for t in TABLES:
        docker("cp", "-n", path(t), path(t) + ".venator-backup")
    print("backed up %s inside the container" % ", ".join(TABLES))


def apply():
    backup()

    # ---- shipTypes --------------------------------------------------------
    pull("shipTypes", "srv_shipTypes.json")
    s = json.load(open("srv_shipTypes.json", encoding="utf8"))
    ships = s["ships"]
    tpl = next(x for x in ships if x.get("typeID") == TEMPLATE)
    rec = dict(tpl)
    rec.update({
        "typeID": TYPE_ID,
        "name": NAME,
        "graphicID": GRAPHIC_ID,
        "radius": 568.5,
        "mass": 105200000,
        "volume": 470000,
        "capacity": 750,
        "published": True,
    })
    # Idempotent: re-running has to REPLACE the record, not skip it, or a
    # changed donor hull never reaches the server.
    existing = next((i for i, x in enumerate(ships) if x.get("typeID") == TYPE_ID), None)
    verb = "updated" if existing is not None else "added"
    if existing is not None:
        ships[existing] = rec
    else:
        ships.append(rec)
    s["count"] = len(ships)
    json.dump(s, open("srv_shipTypes.json", "w", encoding="utf8"))
    push("srv_shipTypes.json", "shipTypes")
    print("shipTypes  %s %d (%s), now %d ships" % (verb, TYPE_ID, NAME, len(ships)))

    # ---- itemTypes --------------------------------------------------------
    pull("itemTypes", "srv_itemTypes.json")
    it = json.load(open("srv_itemTypes.json", encoding="utf8"))
    types = it["types"]
    tpl = next(x for x in types if x.get("typeID") == TEMPLATE)
    rec = dict(tpl)
    rec.update({
        "typeID": TYPE_ID,
        "name": NAME,
        "graphicID": GRAPHIC_ID,
        "radius": 568.5,
        "published": True,
    })
    existing = next((i for i, x in enumerate(types) if x.get("typeID") == TYPE_ID), None)
    verb = "updated" if existing is not None else "added"
    if existing is not None:
        types[existing] = rec
    else:
        types.append(rec)
    it["count"] = len(types)
    json.dump(it, open("srv_itemTypes.json", "w", encoding="utf8"))
    push("srv_itemTypes.json", "itemTypes")
    print("itemTypes  %s %d (%s), now %d types" % (verb, TYPE_ID, NAME, len(types)))

    # ---- typeDogma --------------------------------------------------------
    pull("typeDogma", "srv_typeDogma.json")
    d = json.load(open("srv_typeDogma.json", encoding="utf8"))
    types = d["typesByTypeID"]
    verb = "updated" if str(TYPE_ID) in types else "added"
    tpl = types[str(TEMPLATE)]
    rec = json.loads(json.dumps(tpl))          # deep copy
    rec["typeID"] = TYPE_ID
    rec["typeName"] = NAME
    attrs = rec["attributes"]
    for attribute_id, value in ATTRIBUTES.items():
        attrs[str(attribute_id)] = value
    rec["attributeCount"] = len(attrs)
    types[str(TYPE_ID)] = rec
    d["counts"]["types"] = len(types)
    json.dump(d, open("srv_typeDogma.json", "w", encoding="utf8"))
    push("srv_typeDogma.json", "typeDogma")
    print("typeDogma  %s %d with %d attributes" % (verb, TYPE_ID, len(attrs)))
    for attribute_id, value in sorted(ATTRIBUTES.items()):
        print("    attr %-5s = %s" % (attribute_id, value))

    print()
    print("Restart the server container so it reloads its cached tables.")


def revert():
    for t in TABLES:
        docker("cp", path(t) + ".venator-backup", path(t))
    print("restored %s from backup; restart the server" % ", ".join(TABLES))


if __name__ == "__main__":
    {"apply": apply, "revert": revert}[sys.argv[1] if len(sys.argv) > 1 else "apply"]()
