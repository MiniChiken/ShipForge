"""Show a type's dogma attributes with names, for picking edit targets.

    python peek_dogma.py <typeID> [typeID...]
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXPORT = HERE / "fsd_export"

# The handful that matter for slot layout and tank, so the dump is readable.
NAMES = {
    9: "hp (structure)", 12: "lowSlots", 13: "medSlots", 14: "hiSlots",
    101: "launcherSlotsLeft", 102: "turretSlotsLeft",
    263: "shieldCapacity", 265: "armorHP",
    267: "armorEmResonance", 268: "armorExplosiveResonance",
    269: "armorKineticResonance", 270: "armorThermalResonance",
    271: "shieldEmResonance", 272: "shieldExplosiveResonance",
    273: "shieldKineticResonance", 274: "shieldThermalResonance",
    479: "shieldRechargeRate", 552: "signatureRadius",
    76: "maxTargetRange", 192: "maxLockedTargets",
    11: "powerOutput", 1132: "capacity", 38: "capacity2",
    49: "powerLoad", 48: "cpuOutput", 50: "cpuLoad",
}


def load(table, wanted):
    out = {}
    with open(EXPORT / (table + ".jsonl"), "r", encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            key = rec.get("key", rec.get("_key"))
            if key in wanted:
                out[key] = rec
    return out


def main(ids):
    wanted = set(ids)
    types = load("types", wanted)
    dogma = load("typedogma", wanted)
    for tid in ids:
        t = types.get(tid, {})
        v = t.get("value", t)
        print("=" * 72)
        print("typeID %d  group=%s race=%s published=%s"
              % (tid, v.get("groupID"), v.get("raceID"), v.get("published")))
        print("   graphicID=%s radius=%s typeNameID=%s descriptionID=%s"
              % (v.get("graphicID"), v.get("radius"),
                 v.get("typeNameID"), v.get("descriptionID")))
        d = dogma.get(tid, {})
        dv = d.get("value", d)
        attrs = dv.get("dogmaAttributes") or []
        effects = dv.get("dogmaEffects") or []
        print("   %d attributes, %d effects" % (len(attrs), len(effects)))
        for a in attrs:
            aid = a.get("attributeID")
            if aid in NAMES:
                print("      %-5s %-28s %s" % (aid, NAMES[aid], a.get("value")))


if __name__ == "__main__":
    main([int(x) for x in sys.argv[1:]])
