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
EXPORTS = Path(__file__).resolve().parent / "fsd_export"   # pristine baseline

GRAPHIC_ID = 900001
TYPE_ID = 900001
NAME_MESSAGE_ID = 9000001      # appended to every localization_fsd_<lang>.pickle
DESC_MESSAGE_ID = 9000002
ICON_FOLDER = "res:/elysian/ships/venator/icons"
# Maelstrom: Minmatar (race 2) battleship, and the donor that actually carries
# what was asked for. Ship bonuses live in a record's dogmaEffects and every
# hull's are bespoke - comparing Rifter/Rupture/Tempest/Maelstrom/Hurricane
# against Raven/Megathron/Armageddon/Typhoon shows no shared "projectile bonus"
# effect to graft on, so projectile bonuses can only come from cloning a
# projectile hull. The Maelstrom is the shield-tanked one of those (its effects
# are large projectile damage + shield boost amount), which is also the defence
# bias wanted here. The Typhoon is a missile boat and would have given neither.
TEMPLATE_GRAPHIC = 3134        # Maelstrom
TEMPLATE_TYPE = 24694          # Maelstrom

# Fittings: 4 turrets / 8 mid / 4 low, tanked on shields rather than armour.
# attributeID -> new value. Applied as UPDATEs into the cloned record's nested
# dogmaAttributes list; FsdChange paths accept ints, so ("dogmaAttributes", i,
# "value") addresses a single attribute without rewriting the whole list.
SLOT_LAYOUT = {
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
}
SHIELD_TANK = {
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


def attribute_index(record, attribute_id):
    """Position of an attributeID in a record's dogmaAttributes list."""
    for index, attr in enumerate(record.get("dogmaAttributes") or []):
        if attr.get("attributeID") == attribute_id:
            return index
    raise SystemExit("attributeID %d not present on template %d - cannot patch "
                     "a value the donor record does not already carry"
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
                      path=("sofHullName",), value="venator_t1"),
            # Icons resolve as <iconInfo.folder>/<graphicID>_<size>. Cloning the
            # Maelstrom inherited its folder, so the client looked for
            # 900001_64.png inside mb3/icons and found nothing. Point it at our
            # own namespace and publish the rendered set there.
            FsdChange(ChangeOperation.UPDATE, GRAPHIC_ID,
                      path=("iconInfo", "folder"), value=ICON_FOLDER),
        ])
    print("graphicID %d <- clone of %d, sofHullName -> venator_t1, icons -> %s"
          % (GRAPHIC_ID, TEMPLATE_GRAPHIC, ICON_FOLDER))

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
                      path=("radius",), value=568.5),
            # our own localization messages, so it reads "Venator" not "Typhoon"
            FsdChange(ChangeOperation.UPDATE, TYPE_ID,
                      path=("typeNameID",), value=NAME_MESSAGE_ID),
            FsdChange(ChangeOperation.UPDATE, TYPE_ID,
                      path=("descriptionID",), value=DESC_MESSAGE_ID),
        ])
    print("typeID    %d <- clone of %d, graphicID -> %d, radius -> 568.5, "
          "typeNameID -> %d, descriptionID -> %d"
          % (TYPE_ID, TEMPLATE_TYPE, GRAPHIC_ID, NAME_MESSAGE_ID, DESC_MESSAGE_ID))

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
    dogma_changes = [FsdChange(ChangeOperation.INSERT, TYPE_ID,
                               value=copy.deepcopy(template))]
    for attribute_id, new_value in list(SLOT_LAYOUT.items()) + list(SHIELD_TANK.items()):
        index = attribute_index(template, attribute_id)
        dogma_changes.append(
            FsdChange(ChangeOperation.UPDATE, TYPE_ID,
                      path=("dogmaAttributes", index, "value"), value=new_value))
    project.change_sets["typedogma"] = FsdChangeSet(
        table_name="typedogma", base_sha256=ddoc.source_sha256,
        changes=dogma_changes)

    attrs = template.get("dogmaAttributes") or []
    effects = template.get("dogmaEffects") or []
    print("typedogma %d <- clone of %d (%d attributes, %d effects), %d values patched"
          % (TYPE_ID, TEMPLATE_TYPE, len(attrs), len(effects), len(dogma_changes) - 1))
    for attribute_id, new_value in list(SLOT_LAYOUT.items()) + list(SHIELD_TANK.items()):
        old = attrs[attribute_index(template, attribute_id)].get("value")
        print("    attr %-5s %12s -> %s" % (attribute_id, old, new_value))

    out = Path(__file__).resolve().parent / "fsd_project.json"
    out.write_text(json.dumps(
        {t: cs.to_dict() for t, cs in project.change_sets.items()}, indent=1))
    print("wrote %s" % out)
    return project, profile


if __name__ == "__main__":
    main()
