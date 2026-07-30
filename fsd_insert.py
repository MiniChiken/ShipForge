"""Insert the Venator's graphicID and typeID into the client's FSD tables.

ALL changes go in ONE pass. The Elysian compiler's per-table proofs are bound to
the pristine table MD5s, so once a bundle is applied the 149-table gate refuses
further edits ("mutation verification has not passed"). Roll back to baseline and
re-apply the complete change set rather than layering a second bundle.

Two compiler constraints shape the change list:
  * an INSERT's value must EXACTLY equal an existing record - the compiler clones
    that record's bytes and rekeys it, so every field change is a later UPDATE
  * every patch is validated by a native probe, which needs py27shim.exe installed
    as <repo>/tools/.elysian-suite/runtime/python27/python.exe
"""
import copy
import json
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent / "kit" / \
    "EVE-New-Ship-Native-Authoring-Kit-build3396210" / "fsd-reference"
sys.path.insert(0, str(KIT))

from elysian_fsd.discovery import discover_build_profile          # noqa: E402
from elysian_fsd.documents import DocumentLoader                  # noqa: E402
from elysian_fsd.models import ChangeOperation, FsdChange, FsdChangeSet  # noqa: E402
from elysian_fsd.project import FsdProject                        # noqa: E402

CLIENT = Path(r"C:\EVE-EVEJS\client\EVE\tq")
HERE = Path(__file__).resolve().parent
EXPORTS = HERE / "fsd_export"   # pristine baseline

# ---------------------------------------------------------------------------
# A ShipForge project, when there is one, is the source of truth for the donor
# hull, the stats and the hull bonuses. The constants below are the fallback so
# this module still runs standalone.
#
#   SHIPFORGE_PROJECT=<path to project json>  python fsd_insert.py
# ---------------------------------------------------------------------------
def load_project():
    import os
    explicit = os.environ.get("SHIPFORGE_PROJECT")
    candidates = [Path(explicit)] if explicit else []
    candidates.append(HERE / "shipforge" / "projects" / "venator.json")
    for path in candidates:
        if path.is_file():
            try:
                return json.loads(path.read_text("utf-8")), path
            except ValueError:
                pass
    return {}, None


PROJECT, PROJECT_PATH = load_project()

GRAPHIC_ID = int(PROJECT.get("graphicID") or PROJECT.get("typeID") or 900001)
TYPE_ID = int(PROJECT.get("typeID") or 900001)
NAME_MESSAGE_ID = 9000001      # appended to every localization_fsd_<lang>.pickle
DESC_MESSAGE_ID = 9000002
ICON_FOLDER = PROJECT.get("iconFolder") or "res:/elysian/ships/venator/icons"
SOF_FACTION = PROJECT.get("sofFaction") or "amarrbase"
SOF_RACE = PROJECT.get("sofRace") or "amarr"
SOF_HULL = PROJECT.get("hullName") or "venator_t1"
RADIUS = float(PROJECT.get("radius") or 568.5)
# Maelstrom: Minmatar (race 2) battleship, and the donor that actually carries
# what was asked for. Ship bonuses live in a record's dogmaEffects and every
# hull's are bespoke - comparing Rifter/Rupture/Tempest/Maelstrom/Hurricane
# against Raven/Megathron/Armageddon/Typhoon shows no shared "projectile bonus"
# effect to graft on, so projectile bonuses can only come from cloning a
# projectile hull. The Maelstrom is the shield-tanked one of those (its effects
# are large projectile damage + shield boost amount), which is also the defence
# bias wanted here. The Typhoon is a missile boat and would have given neither.
TEMPLATE_GRAPHIC = int(PROJECT.get("donorGraphicID") or 3134)   # Maelstrom
TEMPLATE_TYPE = int(PROJECT.get("donorTypeID") or 24694)        # Maelstrom

# Stat overrides: attributeID -> value. Applied as UPDATEs into the cloned
# record's nested dogmaAttributes list; FsdChange paths accept ints, so
# ("dogmaAttributes", i, "value") addresses one attribute without rewriting the
# list. An attribute the donor does not already carry cannot be added, because
# an INSERT's value must byte-match an existing record.
#
# Hull bonuses are the record's dogmaEffects. Those CAN be swapped in place, by
# the same path trick on ("dogmaEffects", i, "effectID") - but the LIST LENGTH is
# fixed by the donor, so the donor sets how many bonuses the ship can have.
DEFAULT_ATTRIBUTES = {
    # hiSlots MUST equal the number of turret locator groups on the hull.
    # TurretSet.GetSlotFromModuleFlagID maps a fitted turret to
    # locator_turret_<high slot index + 1>, so with 5 high slots and 4 groups a
    # turret in the last high slot resolves to locator_turret_5* and renders
    # nothing. Four and four means every high slot has somewhere to mount.
    14: 4.0,     # hiSlots
    102: 4.0,    # turretSlotsLeft   (Maelstrom 6)
    101: 0.0,    # launcherSlotsLeft - stays a pure gunship
    13: 8.0,     # medSlots          (Maelstrom 7)
    12: 4.0,     # lowSlots          (Maelstrom 5)
    263: 15000.0,    # shieldCapacity  (Maelstrom 8800)
    265: 5500.0,     # armorHP         (Maelstrom 8250) - deliberately weaker
    9: 9000.0,       # structure hp    (Maelstrom 7700) - a 1137m hull
    271: 0.75,       # shieldEmResonance        (1.0)  lower resonance = tougher
    272: 0.4,        # shieldExplosiveResonance (0.5)
    273: 0.5,        # shieldKineticResonance   (0.6)
    274: 0.65,       # shieldThermalResonance   (0.8)
    479: 1800000.0,  # shieldRechargeRate       (2500000) lower = faster
    552: 500.0,      # signatureRadius          (400) - it is a very large ship
}


def stat_overrides():
    """attributeID -> value, from the project when it defines any."""
    raw = PROJECT.get("dogmaAttributes")
    if not raw:
        return dict(DEFAULT_ATTRIBUTES)
    return {int(k): float(v) for k, v in raw.items()}


def effect_overrides():
    """Slot index -> effectID, for swapping hull bonuses in place."""
    raw = PROJECT.get("dogmaEffects") or []
    return {index: int(effect_id) for index, effect_id in enumerate(raw)}


def attribute_index(record, attribute_id):
    """Position of an attributeID in a record's dogmaAttributes list."""
    for index, attr in enumerate(record.get("dogmaAttributes") or []):
        if attr.get("attributeID") == attribute_id:
            return index
    raise SystemExit("attributeID %d not present on donor %d - an attribute the "
                     "donor record does not already carry cannot be added, "
                     "because an INSERT must byte-match an existing record. "
                     "Pick a donor that has it."
                     % (attribute_id, TEMPLATE_TYPE))


def main():
    profile = discover_build_profile(CLIENT)
    print("client build %s (%s)" % (profile.build, profile.version))

    loader = DocumentLoader(profile, export_root=EXPORTS)
    project = FsdProject(project_id="venator", name="Venator",
                         build=profile.build, profile_id=profile.profile_id)

    # ---- graphicids -------------------------------------------------------
    gdoc = loader.load("graphicids")
    if GRAPHIC_ID in gdoc.records:
        raise SystemExit("graphicID %d already exists" % GRAPHIC_ID)
    project.change_sets["graphicids"] = FsdChangeSet(
        table_name="graphicids", base_sha256=gdoc.source_sha256,
        changes=[
            FsdChange(ChangeOperation.INSERT, GRAPHIC_ID,
                      value=copy.deepcopy(gdoc.records[TEMPLATE_GRAPHIC])),
            FsdChange(ChangeOperation.UPDATE, GRAPHIC_ID,
                      path=("sofHullName",), value=SOF_HULL),
            # Icons resolve as <iconInfo.folder>/<graphicID>_<size>. Cloning the
            # Maelstrom inherited its folder, so the client looked for
            # 900001_64.png inside mb3/icons and found nothing. Point it at our
            # own namespace and publish the rendered set there.
            FsdChange(ChangeOperation.UPDATE, GRAPHIC_ID,
                      path=("iconInfo", "folder"), value=ICON_FOLDER),
            # SOF faction decides which MATERIALS the _m map's four bands select,
            # and the two factions do not agree:
            #   amarrbase    Primary m1 = white_ivory_matt      (bright)
            #   minmatarbase Primary m1 = black_gunmetal_brushed (black)
            # The _m map puts ~93% of this hull on band 1, so inheriting
            # minmatarbase from the Maelstrom graphicID tinted almost the whole
            # ship black gunmetal - no albedo value can compensate for that.
            # A Venator is light grey, so it wants the Amarr material set. This
            # is purely visual; the projectile and shield bonuses come from
            # typedogma, which is a different table and unaffected.
            FsdChange(ChangeOperation.UPDATE, GRAPHIC_ID,
                      path=("sofFactionName",), value=SOF_FACTION),
            FsdChange(ChangeOperation.UPDATE, GRAPHIC_ID,
                      path=("sofRaceName",), value=SOF_RACE),
        ])
    print("graphicID %d <- clone of %d, sofHullName -> %s, faction -> %s/%s, "
          "icons -> %s" % (GRAPHIC_ID, TEMPLATE_GRAPHIC, SOF_HULL, SOF_FACTION,
                           SOF_RACE, ICON_FOLDER))
    if PROJECT_PATH:
        print("   (driven by %s)" % PROJECT_PATH)

    # ---- types ------------------------------------------------------------
    tdoc = loader.load("types")
    if TYPE_ID in tdoc.records:
        raise SystemExit("typeID %d already exists" % TYPE_ID)
    project.change_sets["types"] = FsdChangeSet(
        table_name="types", base_sha256=tdoc.source_sha256,
        changes=[
            FsdChange(ChangeOperation.INSERT, TYPE_ID,
                      value=copy.deepcopy(tdoc.records[TEMPLATE_TYPE])),
            FsdChange(ChangeOperation.UPDATE, TYPE_ID,
                      path=("graphicID",), value=GRAPHIC_ID),
            FsdChange(ChangeOperation.UPDATE, TYPE_ID,
                      path=("typeID",), value=TYPE_ID),
            # half the hull's long axis, matching how EVE sizes ship radius
            FsdChange(ChangeOperation.UPDATE, TYPE_ID,
                      path=("radius",), value=RADIUS),
            # our own localization messages, so it reads "Venator" not "Typhoon"
            FsdChange(ChangeOperation.UPDATE, TYPE_ID,
                      path=("typeNameID",), value=NAME_MESSAGE_ID),
            FsdChange(ChangeOperation.UPDATE, TYPE_ID,
                      path=("descriptionID",), value=DESC_MESSAGE_ID),
        ])
    print("typeID    %d <- clone of %d, graphicID -> %d, radius -> %s, "
          "typeNameID -> %d, descriptionID -> %d"
          % (TYPE_ID, TEMPLATE_TYPE, GRAPHIC_ID, RADIUS,
             NAME_MESSAGE_ID, DESC_MESSAGE_ID))

    # ---- typedogma --------------------------------------------------------
    # The CLIENT computes HP bars and the fitting window's slot layout from its
    # own typedogma table, not from the server. Without a row here max HP
    # resolves to 0 (hull renders destroyed) and there are no module slots.
    # An exact clone of the Armageddon carries hp/armorHP/shieldCapacity plus
    # hiSlots/medSlots/lowSlots/turretSlotsLeft/launcherSlotsLeft.
    ddoc = loader.load("typedogma")
    if TYPE_ID in ddoc.records:
        raise SystemExit("typedogma %d already exists" % TYPE_ID)
    template = ddoc.records[TEMPLATE_TYPE]
    attrs = template.get("dogmaAttributes") or []
    effects = template.get("dogmaEffects") or []
    overrides = stat_overrides()
    swaps = effect_overrides()

    dogma_changes = [FsdChange(ChangeOperation.INSERT, TYPE_ID,
                               value=copy.deepcopy(template))]

    # Attributes the donor does NOT carry can still be added: the byte-match rule
    # constrains the INSERT, but an UPDATE assigns target[path[-1]] = value, so an
    # update at ("dogmaAttributes",) replaces the WHOLE LIST. That decouples what
    # a ship can do from whichever donor happened to be cloned - without it, any
    # new bonus mechanism means hunting for a hull that already has the attribute.
    carried = {a.get("attributeID") for a in attrs}
    added = sorted(a for a in overrides if a not in carried)
    if added:
        new_list = copy.deepcopy(attrs)
        for attribute_id in added:
            entry = copy.deepcopy(attrs[0])
            entry["attributeID"] = attribute_id
            entry["value"] = overrides[attribute_id]
            new_list.append(entry)
        for entry in new_list:
            if entry.get("attributeID") in overrides:
                entry["value"] = overrides[entry["attributeID"]]
        dogma_changes.append(
            FsdChange(ChangeOperation.UPDATE, TYPE_ID,
                      path=("dogmaAttributes",), value=new_list))
    else:
        for attribute_id, new_value in sorted(overrides.items()):
            index = attribute_index(template, attribute_id)
            dogma_changes.append(
                FsdChange(ChangeOperation.UPDATE, TYPE_ID,
                          path=("dogmaAttributes", index, "value"),
                          value=new_value))

    # Hull bonuses. The list LENGTH is fixed by the donor - a longer list cannot
    # be authored through path updates - so a project can only replace the
    # bonuses in the slots the donor already has.
    if swaps:
        if max(swaps) >= len(effects):
            # longer than the donor's list: replace it wholesale, same trick as
            # the attributes above. The donor no longer caps how many bonuses a
            # ship can have.
            new_effects = []
            for index in range(max(swaps) + 1):
                entry = copy.deepcopy(effects[min(index, len(effects) - 1)])
                entry["effectID"] = swaps[index] if index in swaps \
                    else effects[index]["effectID"]
                new_effects.append(entry)
            dogma_changes.append(
                FsdChange(ChangeOperation.UPDATE, TYPE_ID,
                          path=("dogmaEffects",), value=new_effects))
        else:
            for index, effect_id in sorted(swaps.items()):
                if effects[index].get("effectID") == effect_id:
                    continue
                dogma_changes.append(
                    FsdChange(ChangeOperation.UPDATE, TYPE_ID,
                              path=("dogmaEffects", index, "effectID"),
                              value=effect_id))

    project.change_sets["typedogma"] = FsdChangeSet(
        table_name="typedogma", base_sha256=ddoc.source_sha256,
        changes=dogma_changes)

    print("typedogma %d <- clone of %d (%d attributes, %d effects), %d patches"
          % (TYPE_ID, TEMPLATE_TYPE, len(attrs), len(effects),
             len(dogma_changes) - 1))
    by_id = {a.get("attributeID"): a.get("value") for a in attrs}
    for attribute_id, new_value in sorted(overrides.items()):
        if attribute_id not in by_id:
            print("    attr %-5s %12s -> %s  (ADDED)" % (attribute_id, "-", new_value))
            continue
        old = by_id[attribute_id]
        flag = "" if old != new_value else "  (unchanged)"
        print("    attr %-5s %12s -> %s%s" % (attribute_id, old, new_value, flag))
    for index, effect_id in sorted(swaps.items()):
        if index >= len(effects):
            print("    bonus slot %d  %s -> %s  (ADDED)" % (index, "-", effect_id))
            continue
        old = effects[index].get("effectID")
        print("    bonus slot %d  %s -> %s%s"
              % (index, old, effect_id, "" if old != effect_id else "  (unchanged)"))

    out = Path(__file__).resolve().parent / "fsd_project.json"
    out.write_text(json.dumps(
        {t: cs.to_dict() for t, cs in project.change_sets.items()}, indent=1))
    print("wrote %s" % out)
    return project, profile


if __name__ == "__main__":
    main()
