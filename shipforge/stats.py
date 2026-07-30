"""Ship statistics and hull bonuses, resolved against the client's own metadata.

Editing stats by raw attributeID is unusable, and a hand-written name table
drifts from the build. So names, defaults, units and "is higher better" come from
the client's exported `dogmaattributes` / `dogmaeffects` / `dogmaunits`
(see export_reference.py), and the editable baseline comes from the donor hull's
own typedogma record.

Two constraints the UI has to respect, both from the FSD compiler:

  * an attribute the DONOR does not carry cannot be added, because an INSERT's
    value must byte-match an existing record. Only the donor's own attributes are
    editable.
  * the hull-bonus LIST LENGTH is fixed by the donor. Bonuses can be swapped
    slot-for-slot but not added, so the donor decides how many a ship can have.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
REFERENCE = HERE / "reference"
EXPORTS = TOOLS / "fsd_export"          # pristine baseline tables

# Attribute categories worth surfacing first; everything else is still editable
# but sorted after these.
PRIORITY = (
    ("Fitting", (14, 102, 101, 13, 12, 11, 48, 1547)),
    ("Defence", (9, 265, 263, 479, 552,
                 267, 268, 269, 270, 271, 272, 273, 274)),
    ("Capacitor", (482, 55)),
    ("Targeting", (76, 192, 208, 209, 210, 211, 552)),
    ("Propulsion", (37, 4, 70, 1281)),
    ("Cargo", (38, 1132)),
)


def _load_jsonl(path):
    out = {}
    if not path.is_file():
        return out
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            record = json.loads(line)
            out[record.get("key", record.get("_key"))] = record.get("value", record)
    return out


def attribute_meta():
    return _load_jsonl(REFERENCE / "dogmaattributes.jsonl")


def effect_meta():
    return _load_jsonl(REFERENCE / "dogmaeffects.jsonl")


def unit_meta():
    return _load_jsonl(REFERENCE / "dogmaunits.jsonl")


def _typedogma():
    return _load_jsonl(EXPORTS / "typedogma.jsonl")


def _types():
    return _load_jsonl(EXPORTS / "types.jsonl")


def reference_available():
    return (REFERENCE / "dogmaattributes.jsonl").is_file()


def donor_stats(donor_type_id):
    """Editable stats and bonuses for a donor, with client metadata attached."""
    dogma = _typedogma().get(int(donor_type_id))
    if dogma is None:
        return {"error": "donor typeID %s not in the exported typedogma"
                         % donor_type_id}
    attributes = attribute_meta()
    units = unit_meta()
    effects_meta = effect_meta()

    group_of = {}
    for label, ids in PRIORITY:
        for index, attribute_id in enumerate(ids):
            group_of.setdefault(attribute_id, (label, index))

    rows = []
    for entry in dogma.get("dogmaAttributes") or []:
        attribute_id = entry.get("attributeID")
        meta = attributes.get(attribute_id) or {}
        unit = units.get(meta.get("unitID")) or {}
        label, order = group_of.get(attribute_id, ("Other", 999))
        rows.append({
            "attributeID": attribute_id,
            "name": meta.get("name") or ("attribute %s" % attribute_id),
            "description": (meta.get("description") or "")[:220],
            "donorValue": entry.get("value"),
            "defaultValue": meta.get("defaultValue"),
            "highIsGood": bool(meta.get("highIsGood", 1)),
            "unit": unit.get("name") or "",
            "group": label,
            "order": order,
        })
    rows.sort(key=lambda r: (r["group"] == "Other", r["group"], r["order"],
                             r["name"].lower()))

    bonuses = []
    for index, entry in enumerate(dogma.get("dogmaEffects") or []):
        effect_id = entry.get("effectID")
        meta = effects_meta.get(effect_id) or {}
        bonuses.append({
            "slot": index,
            "effectID": effect_id,
            "effectName": meta.get("effectName") or ("effect %s" % effect_id),
            "isDefault": bool(entry.get("isDefault")),
        })

    return {"donorTypeID": int(donor_type_id),
            "attributes": rows,
            "bonusSlots": bonuses}


def donor_candidates(query="", limit=60):
    """Ships that can act as a donor, with their bonus count and race."""
    types = _types()
    dogma = _typedogma()
    effects_meta = effect_meta()
    needle = (query or "").lower().strip()
    out = []
    for type_id, record in types.items():
        if record.get("groupID") != 27:            # Battleship
            continue
        if not record.get("published"):
            continue
        entry = dogma.get(type_id)
        if entry is None:
            continue
        names = [effects_meta.get(e.get("effectID"), {}).get("effectName", "")
                 for e in (entry.get("dogmaEffects") or [])]
        blob = ("%s %s %s" % (type_id, record.get("raceID"), " ".join(names))).lower()
        if needle and needle not in blob:
            continue
        out.append({
            "typeID": type_id,
            "graphicID": record.get("graphicID"),
            "raceID": record.get("raceID"),
            "bonusCount": len(entry.get("dogmaEffects") or []),
            "attributeCount": len(entry.get("dogmaAttributes") or []),
            "effects": names,
        })
    out.sort(key=lambda r: (-r["bonusCount"], r["typeID"]))
    return out[:limit]


def validate_stats(project):
    """Problems a stat or bonus edit can cause, checked against the donor."""
    problems = []
    donor_type_id = int(project.get("donorTypeID") or 24694)
    dogma = _typedogma().get(donor_type_id)
    if dogma is None:
        return ["donor typeID %d is not in the exported typedogma; re-export or "
                "pick another donor" % donor_type_id]

    carried = {e.get("attributeID") for e in (dogma.get("dogmaAttributes") or [])}
    for raw_id in (project.get("dogmaAttributes") or {}):
        attribute_id = int(raw_id)
        if attribute_id not in carried:
            problems.append(
                "attribute %s is not on donor %d, so it cannot be added - an "
                "INSERT must byte-match an existing record. Pick a donor that "
                "carries it." % (attribute_id, donor_type_id))

    slots = len(dogma.get("dogmaEffects") or [])
    wanted = project.get("dogmaEffects") or []
    if len(wanted) > slots:
        problems.append(
            "%d hull bonuses requested but donor %d has only %d effect slots; "
            "the donor fixes how many a ship can carry"
            % (len(wanted), donor_type_id, slots))

    # the invariant that silently breaks turret rendering
    attributes = {int(k): v for k, v in (project.get("dogmaAttributes") or {}).items()}
    groups = set()
    for turret in project.get("turrets", []):
        digits = "".join(c for c in turret.get("name", "") if c.isdigit())
        if digits:
            groups.add(digits)
    hi_slots = attributes.get(14)
    if groups and hi_slots is not None and int(hi_slots) != len(groups):
        problems.append(
            "hiSlots is %g but the hull has %d turret locator groups; a turret "
            "in a high slot with no matching group renders nothing"
            % (hi_slots, len(groups)))
    return problems
