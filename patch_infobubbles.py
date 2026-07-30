"""Give a custom ship its trait text in the Info panel.

The bonus list in a ship's Information window does NOT come from the cFSD tables,
which is why a ship with working dogmaEffects can still show nothing.
traits.pyj asks infobubbles.has_traits(typeID), and that is just membership of

    fsdlite.EveStorage(data='infoBubbleElements', cache='infoBubbles.static')
        ['infoBubbleTypeBonuses']

That resource - res:/staticdata/infobubbles.static - turns out to be a plain
SQLite database with a cache(key TEXT, value TEXT, time FLOAT) table whose values
are JSON, so it needs no client involvement at all. fsdlite's own encoder.py
confirms the payload is yaml/ujson; the .static wrapper is its SQLite cache.

Entry shape, per typeID:

    {"types": {"<skillTypeID>": [{"bonus", "importance", "nameID", "unitID"}]},
     "roleBonuses": [...], "miscBonuses": [...]}

`nameID` is a localization message, so cloning the DONOR's entry gives text that
matches the bonuses the ship actually has - it carries the donor's dogmaEffects.

    python patch_infobubbles.py            # write and publish
    python patch_infobubbles.py --dry-run
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CLIENT = Path(r"C:\EVE-EVEJS\client\EVE")
INDEX = CLIENT / "tq" / "resfileindex.txt"
RESOURCE = "res:/staticdata/infobubbles.static"
OUT = HERE / "native_out" / "infobubbles.static"
KEY = "infoBubbleTypeBonuses"


def project():
    for path in ([Path(os.environ["SHIPFORGE_PROJECT"])]
                 if os.environ.get("SHIPFORGE_PROJECT") else []) + [
            HERE / "shipforge" / "projects" / "venator.json"]:
        if path.is_file():
            return json.loads(path.read_text("utf-8"))
    return {}


def pristine_blob():
    """The blob the index currently points at for this resource."""
    with INDEX.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.rstrip("\n").split(",")
            if parts and parts[0].lower() == RESOURCE:
                return CLIENT / "ResFiles" / parts[1].replace("/", os.sep)
    raise SystemExit("%s is not in the index" % RESOURCE)


def main(dry_run):
    proj = project()
    type_id = str(int(proj.get("typeID") or 900001))
    donor_id = str(int(proj.get("donorTypeID") or 24694))

    source = pristine_blob()
    OUT.parent.mkdir(exist_ok=True)
    shutil.copy2(source, OUT)
    print("source blob : %s (%d bytes)" % (source.name, source.stat().st_size))

    con = sqlite3.connect(str(OUT))
    try:
        rows = dict(con.execute("select key, value from cache"))
        if KEY not in rows:
            raise SystemExit("%s missing from the cache table" % KEY)
        bonuses = json.loads(rows[KEY])
        print("entries     : %d" % len(bonuses))

        donor = bonuses.get(donor_id)
        if donor is None:
            raise SystemExit("donor typeID %s has no trait entry - pick a donor "
                             "that does, or the panel has nothing to clone"
                             % donor_id)

        already = type_id in bonuses
        bonuses[type_id] = json.loads(json.dumps(donor))    # deep copy
        skills = ", ".join(sorted(donor.get("types", {})))
        print("%s typeID %s from donor %s"
              % ("updated" if already else "added", type_id, donor_id))
        print("   skill bonus groups : %s" % (skills or "none"))
        print("   role bonuses       : %d" % len(donor.get("roleBonuses") or []))
        print("   misc bonuses       : %d" % len(donor.get("miscBonuses") or []))

        if dry_run:
            con.rollback()
            print("\ndry run - nothing written")
            return
        con.execute("update cache set value = ? where key = ?",
                    (json.dumps(bonuses, separators=(",", ":")), KEY))
        con.commit()
    finally:
        con.close()

    print("wrote %s (%d bytes)" % (OUT, OUT.stat().st_size))
    subprocess.run([sys.executable, str(HERE / "install.py"),
                    "--publish", RESOURCE, str(OUT)], check=True)


if __name__ == "__main__":
    main("--dry-run" in sys.argv)
