"""Read the PATCHED client FSD tables back and check typeID 900001.

Deliberately does not reuse Run-Fsd-Export.ps1: that writes into fsd_export,
which is the pristine baseline the change sets are built against. This resolves
each table's CURRENT blob from the live resfileindex and exports to fsd_verify
instead, so the baseline is left alone.

    python verify_fsd.py tasks     # stage export tasks against the live tables
    python verify_fsd.py report    # read the exported rows back
"""
import json
import sys
from pathlib import Path

import fsd_insert
from fsd_insert import KIT  # noqa: F401  (sets sys.path for elysian_fsd)

from elysian_fsd.discovery import discover_build_profile  # noqa: E402

HERE = Path(__file__).resolve().parent
CLIENT = Path(r"C:\EVE-EVEJS\client\EVE")
INDEX = CLIENT / "tq" / "resfileindex.txt"
OUT = HERE / "fsd_verify"
WORK = HERE / "fsd_verify_work"
TABLES = ("graphicids", "types", "typedogma")
TYPE_ID = 900001


def index_map():
    rows = {}
    with open(INDEX, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.rstrip("\n").split(",")
            if len(parts) >= 2:
                rows[parts[0].lower()] = parts[1]
    return rows


def tasks():
    profile = discover_build_profile(CLIENT / "tq")
    rows = index_map()
    OUT.mkdir(exist_ok=True)
    WORK.mkdir(exist_ok=True)
    entries = []
    for name in TABLES:
        table = profile.tables[name]
        blob = rows[table.logical_path.lower()]
        task = WORK / ("task-%s.json" % name)
        task.write_text(json.dumps({
            "tableName": name,
            "loaderModule": table.loader_module,
            "resourcePath": str(CLIENT / "ResFiles" / blob.replace("/", "\\")),
            "outputPath": str(OUT / ("%s.jsonl" % name)),
            "rootValueProjection": False,
            "singletonObjectRoot": False,
        }, indent=1), "utf-8")
        entries.append([name, str(task), str(WORK / ("result-%s.json" % name))])
        print("%-11s %s -> %s" % (name, table.logical_path, blob))
    (WORK / "tasks.json").write_text(json.dumps(entries, indent=1), "utf-8")
    print("wrote %s" % (WORK / "tasks.json"))


def load(table):
    out = {}
    with open(OUT / ("%s.jsonl" % table), "r", encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            out[rec.get("key", rec.get("_key"))] = rec
    return out


def report():
    graphics = load("graphicids")
    types = load("types")
    dogma = load("typedogma")

    g = graphics.get(TYPE_ID)
    print("graphicID %d present: %s" % (TYPE_ID, g is not None))
    if g:
        gv = g.get("value", g)
        print("   sofHullName = %r" % gv.get("sofHullName"))

    t = types.get(TYPE_ID)
    print("typeID    %d present: %s" % (TYPE_ID, t is not None))
    if t:
        tv = t.get("value", t)
        for field in ("graphicID", "radius", "typeNameID", "descriptionID",
                      "raceID", "groupID"):
            print("   %-14s %s" % (field, tv.get(field)))

    d = dogma.get(TYPE_ID)
    print("typedogma %d present: %s" % (TYPE_ID, d is not None))
    if d:
        dv = d.get("value", d)
        attrs = {a["attributeID"]: a["value"] for a in (dv.get("dogmaAttributes") or [])}
        effects = [e.get("effectID") for e in (dv.get("dogmaEffects") or [])]
        expected = dict(fsd_insert.SLOT_LAYOUT)
        expected.update(fsd_insert.SHIELD_TANK)
        ok = True
        for attribute_id, want in sorted(expected.items()):
            got = attrs.get(attribute_id)
            good = got == want
            ok = ok and good
            print("   attr %-5s want %-12s got %-12s %s"
                  % (attribute_id, want, got, "OK" if good else "MISMATCH"))
        print("   effects (Maelstrom projectile/shield bonuses): %s" % effects)
        print("   ALL ATTRIBUTES MATCH: %s" % ok)


if __name__ == "__main__":
    {"tasks": tasks, "report": report}[sys.argv[1] if len(sys.argv) > 1 else "tasks"]()
