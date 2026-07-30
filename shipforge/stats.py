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


# --------------------------------------------------------------- legibility
# EVE dogma operation codes. Only the ones ship bonuses actually use are named
# specially; the rest fall through to "<op> <value>".
OPERATIONS = {0: "set to", 1: "premul", 2: "prediv", 3: "add", 4: "subtract",
              5: "postmul", 6: "percent", 7: "postdiv", 8: "set to"}

_LOCALIZATION = {}


def prettify(name):
    """camelCase attribute identifier -> readable words."""
    if not name:
        return ""
    out = []
    for index, char in enumerate(str(name)):
        if char.isupper() and index and not str(name)[index - 1].isupper():
            out.append(" ")
        out.append(char)
    text = "".join(out).replace("_", " ").strip()
    return text[:1].upper() + text[1:]


def _localization():
    """messageID -> English text, from the localization pickle we author into.

    Effect, attribute and group NAMES in the tables are internal identifiers;
    the human wording lives in localization, so legible bonus text needs both.
    """
    global _LOCALIZATION
    if _LOCALIZATION:
        return _LOCALIZATION
    import pickle
    for candidate in (TOOLS / "loc_out" / "localization_fsd_en-us.pickle",
                      TOOLS / "loc_out" / "localization_fsd_main.pickle"):
        if not candidate.is_file():
            continue
        try:
            with candidate.open("rb") as fh:
                blob = pickle.load(fh, encoding="latin1")
            messages = blob[1] if isinstance(blob, tuple) else blob
            _LOCALIZATION = {k: (v[0] if isinstance(v, (tuple, list)) else v)
                             for k, v in messages.items()}
            break
        except Exception:
            continue
    return _LOCALIZATION


def type_name(type_id):
    record = _types().get(type_id) or {}
    return _localization().get(record.get("typeNameID")) or ("type %s" % type_id)


def group_name(group_id):
    groups = _load_jsonl(REFERENCE / "groups.jsonl")
    record = groups.get(group_id) or {}
    return _localization().get(record.get("groupNameID")) or ("group %s" % group_id)


def describe_effect(effect_id, donor_attributes=None):
    """Plain-English reading of a hull bonus, from its modifierInfo.

    A bonus is not stored as text anywhere - it is a list of modifiers saying
    "scale attribute X on things matching Y by the ship's attribute Z". The
    magnitude therefore lives on the DONOR's own attributes, which is why
    donor_attributes is needed to say "+10%" rather than "+shipBonusMB2%".
    """
    meta = effect_meta().get(effect_id) or {}
    attributes = attribute_meta()
    donor_attributes = donor_attributes or {}
    lines = []
    for modifier in (meta.get("modifierInfo") or []):
        modified = attributes.get(modifier.get("modifiedAttributeID")) or {}
        what = prettify(modified.get("name")) or (
            "attribute %s" % modifier.get("modifiedAttributeID"))

        amount_id = modifier.get("modifyingAttributeID")
        amount = donor_attributes.get(amount_id)
        operation = OPERATIONS.get(modifier.get("operation"), "modify")
        if amount is None:
            magnitude = prettify((attributes.get(amount_id) or {}).get("name")) or "?"
        elif operation == "percent":
            magnitude = "%+g%%" % amount
        else:
            magnitude = "%g" % amount

        if modifier.get("skillTypeID"):
            target = "modules requiring %s" % type_name(modifier["skillTypeID"])
        elif modifier.get("groupID"):
            target = "%s modules" % group_name(modifier["groupID"])
        else:
            target = "the ship"

        verb = magnitude if operation == "percent" else "%s %s" % (operation, magnitude)
        lines.append("%s %s on %s" % (verb, what, target))

    if not lines:
        return meta.get("effectName") or ("effect %s" % effect_id)
    per_level = " per skill level" if any(
        m.get("func") == "LocationRequiredSkillModifier"
        for m in (meta.get("modifierInfo") or [])) else ""
    return "; ".join(lines) + per_level


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
            "label": prettify(meta.get("name")) or ("Attribute %s" % attribute_id),
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

    own = {e.get("attributeID"): e.get("value")
           for e in (dogma.get("dogmaAttributes") or [])}
    bonuses = []
    for index, entry in enumerate(dogma.get("dogmaEffects") or []):
        effect_id = entry.get("effectID")
        meta = effects_meta.get(effect_id) or {}
        bonuses.append({
            "slot": index,
            "effectID": effect_id,
            "effectName": meta.get("effectName") or ("effect %s" % effect_id),
            "text": describe_effect(effect_id, own),
            "isDefault": bool(entry.get("isDefault")),
        })

    return {"donorTypeID": int(donor_type_id),
            "donorName": type_name(int(donor_type_id)),
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
