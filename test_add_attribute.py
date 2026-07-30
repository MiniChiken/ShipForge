"""Can a NEW dogma attribute be added, or only existing ones retuned?

The rule everything has been built around is that an INSERT's value must exactly
match an existing record, so a custom ship inherits whichever attributes and
effects its donor happens to carry. That is what forces a donor hunt for any
bonus mechanism.

But that rule constrains INSERT. An UPDATE does

    target = record; for c in path[:-1]: target = target[c]
    target[path[-1]] = value

so an UPDATE at path ("dogmaAttributes",) replaces the WHOLE LIST - which would
add attributes and effects freely, and remove the donor constraint entirely.

This compiles such a change in memory and round-trips it. It touches nothing:
no bundle is staged, no client file is written.

    python test_add_attribute.py
"""
import copy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "kit" /
                       "EVE-New-Ship-Native-Authoring-Kit-build3396210" /
                       "fsd-reference"))

from elysian_fsd.discovery import discover_build_profile          # noqa: E402
from elysian_fsd.documents import DocumentLoader                  # noqa: E402
from elysian_fsd.models import ChangeOperation, FsdChange, FsdChangeSet  # noqa: E402

CLIENT = Path(r"C:\EVE-EVEJS\client\EVE\tq")
EXPORTS = HERE / "fsd_export"

TYPE_ID = 900001
DONOR = 24694          # Maelstrom - does NOT carry 1268
NEW_ATTRIBUTE = 1268   # eliteBonusViolatorsRole1, carried only by Marauders
NEW_EFFECT = 3417      # large-projectile damage as a flat role bonus


def main():
    profile = discover_build_profile(CLIENT)
    loader = DocumentLoader(profile, export_root=EXPORTS)
    document = loader.load("typedogma")
    donor = document.records[DONOR]

    attributes = copy.deepcopy(donor.get("dogmaAttributes") or [])
    effects = copy.deepcopy(donor.get("dogmaEffects") or [])
    print("donor %d: %d attributes, %d effects"
          % (DONOR, len(attributes), len(effects)))
    print("  carries %d already: %s"
          % (NEW_ATTRIBUTE,
             any(a.get("attributeID") == NEW_ATTRIBUTE for a in attributes)))

    # what an "add" looks like: append, then replace the whole list
    sample = dict(attributes[0])
    sample["attributeID"] = NEW_ATTRIBUTE
    sample["value"] = 200.0
    attributes.append(sample)

    sample_effect = dict(effects[0])
    sample_effect["effectID"] = NEW_EFFECT
    effects.append(sample_effect)

    changes = [
        FsdChange(ChangeOperation.INSERT, TYPE_ID, value=copy.deepcopy(donor)),
        FsdChange(ChangeOperation.UPDATE, TYPE_ID,
                  path=("dogmaAttributes",), value=attributes),
        FsdChange(ChangeOperation.UPDATE, TYPE_ID,
                  path=("dogmaEffects",), value=effects),
    ]
    change_set = FsdChangeSet(table_name="typedogma",
                              base_sha256=document.source_sha256,
                              changes=changes)

    # apply them the way prepare_fsd_bundle does
    from elysian_fsd import deployment
    applied = deployment._apply_changes(loader.load("typedogma"), change_set)
    record = applied.records[TYPE_ID]
    got_attributes = record.get("dogmaAttributes") or []
    got_effects = record.get("dogmaEffects") or []
    print()
    print("after applying the change set:")
    print("  attributes %d -> %d" % (len(donor.get("dogmaAttributes") or []),
                                     len(got_attributes)))
    print("  effects    %d -> %d" % (len(donor.get("dogmaEffects") or []),
                                     len(got_effects)))
    print("  %d present: %s  value %s"
          % (NEW_ATTRIBUTE,
             any(a.get("attributeID") == NEW_ATTRIBUTE for a in got_attributes),
             next((a.get("value") for a in got_attributes
                   if a.get("attributeID") == NEW_ATTRIBUTE), None)))
    print("  effect %d present: %s"
          % (NEW_EFFECT,
             any(e.get("effectID") == NEW_EFFECT for e in got_effects)))

    # the real question: does the binary compiler accept the longer lists
    print()
    print("compiling the table...")
    compiler = deployment.build_compiler(profile) \
        if hasattr(deployment, "build_compiler") else None
    if compiler is None:
        from elysian_fsd.compiler import FsdCompiler
        try:
            compiler = FsdCompiler(profile)
        except TypeError:
            compiler = FsdCompiler()
    compiled = compiler.compile(applied)
    print("  OK: %d bytes, md5 %s" % (len(compiled.payload), compiled.md5))
    print()
    print("=> adding attributes and effects IS possible; the donor only has to")
    print("   supply a byte-matching record for the INSERT.")


if __name__ == "__main__":
    main()
