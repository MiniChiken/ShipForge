"""Export the client's dogma reference tables, so stats can be edited by NAME.

Attribute and effect metadata lives in the client, not in this repo:
`dogmaattributes` (names, defaults, units, high-is-good), `dogmaeffects` (what a
ship bonus actually is) and `dogmaunits` (how to display a value). Exporting them
means ShipForge can label a stat "shieldCapacity - Shield Capacity (HP)" rather
than relying on a hand-written lookup that will drift from the build.

Read-only: resolves whatever blob the LIVE resfileindex points at and runs the
same worker the verification path uses. Writes to shipforge/reference/.

    python export_reference.py stage     # write the task files
    python export_reference.py load      # read the exported rows back
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
sys.path.insert(0, str(TOOLS / "kit" /
                       "EVE-New-Ship-Native-Authoring-Kit-build3396210" /
                       "fsd-reference"))

from elysian_fsd.discovery import discover_build_profile      # noqa: E402

CLIENT = Path(r"C:\EVE-EVEJS\client\EVE")
INDEX = CLIENT / "tq" / "resfileindex.txt"
OUT = HERE / "reference"
WORK = HERE / "reference_work"
TABLES = ("dogmaattributes", "dogmaeffects", "dogmaunits", "groups")


def index_map():
    rows = {}
    with INDEX.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.rstrip("\n").split(",")
            if len(parts) >= 2:
                rows[parts[0].lower()] = parts[1]
    return rows


def stage():
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
        print("%-18s %s -> %s" % (name, table.logical_path, blob))
    (WORK / "tasks.json").write_text(json.dumps(entries, indent=1), "utf-8")
    print("wrote %s" % (WORK / "tasks.json"))


def load_table(name):
    path = OUT / ("%s.jsonl" % name)
    if not path.is_file():
        return {}
    out = {}
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            record = json.loads(line)
            key = record.get("key", record.get("_key"))
            out[key] = record.get("value", record)
    return out


def load():
    attributes = load_table("dogmaattributes")
    effects = load_table("dogmaeffects")
    units = load_table("dogmaunits")
    print("dogmaattributes %d, dogmaeffects %d, dogmaunits %d"
          % (len(attributes), len(effects), len(units)))
    for key in list(attributes)[:3]:
        print("  attr %s -> %s" % (key, json.dumps(attributes[key])[:220]))
    for key in list(effects)[:2]:
        print("  effect %s -> %s" % (key, json.dumps(effects[key])[:220]))
    for key in list(units)[:3]:
        print("  unit %s -> %s" % (key, json.dumps(units[key])[:160]))
    return attributes, effects, units


if __name__ == "__main__":
    {"stage": stage, "load": load}[sys.argv[1] if len(sys.argv) > 1 else "stage"]()
