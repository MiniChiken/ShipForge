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

The one thing a clone gets wrong is the MAGNITUDE. Each entry stores its own
number, so retuning the attribute a bonus reads leaves the panel quoting the
donor's figure while the ship does something else - the displayed-value-disagrees
-with-reality bug this project keeps hitting. `retune` fixes those numbers up.

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
sys.path.insert(0, str(HERE / "shipforge"))
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


def retune(entry, proj, donor_id):
    """Rewrite cloned trait magnitudes to the project's own attribute values.

    Entries carry no link back to the effect they describe, so they are matched
    by the DONOR value they were written from, inside the section the effect
    belongs to: a shipBonus* attribute scales per skill level and so appears
    under "types", everything else is a flat role bonus. Only attributes some
    effect on the hull actually reads are considered. An ambiguous or missing
    match is reported rather than guessed at - a wrong number here is worse than
    an unchanged one, because it reads as authoritative.
    """
    import stats

    overrides = {int(k): v for k, v in (proj.get("dogmaAttributes") or {}).items()}
    dogma = stats._typedogma().get(int(donor_id)) or {}
    donor_values = {a["attributeID"]: a["value"]
                    for a in (dogma.get("dogmaAttributes") or [])}
    meta = stats.attribute_meta()

    # attributeID -> is it read by one of this hull's bonuses, and how
    read_by_bonus = {}
    for slot in (dogma.get("dogmaEffects") or []):
        effect = stats.effect_meta().get(slot.get("effectID")) or {}
        for modifier in (effect.get("modifierInfo") or []):
            read_by_bonus[modifier.get("modifyingAttributeID")] = slot["effectID"]

    for attribute_id, wanted in sorted(overrides.items()):
        if attribute_id not in read_by_bonus:
            continue                       # a plain stat, not a bonus magnitude
        was = donor_values.get(attribute_id)
        if was is None or was == wanted:
            continue

        name = (meta.get(attribute_id) or {}).get("name") or ""
        per_level = name.lower().startswith("shipbonus") and "role" not in name.lower()
        if per_level:
            sections = [("types[%s]" % skill, rows)
                        for skill, rows in (entry.get("types") or {}).items()]
        else:
            sections = [("roleBonuses", entry.get("roleBonuses") or [])]

        hits = [(where, row) for where, rows in sections
                for row in rows if row.get("bonus") == was]
        label = "attr %d (%s) %g -> %g" % (attribute_id, name, was, wanted)
        if len(hits) == 1:
            where, row = hits[0]
            row["bonus"] = wanted
            print("   retuned %s in %s" % (label, where))
        elif not hits:
            print("   NO trait entry quotes %g for %s - panel text will not "
                  "mention it" % (was, label))
        else:
            print("   AMBIGUOUS %s: %d entries quote %g (%s) - left alone"
                  % (label, len(hits), was, ", ".join(w for w, _ in hits)))


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
        entry = json.loads(json.dumps(donor))               # deep copy
        bonuses[type_id] = entry
        retune(entry, proj, donor_id)
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
