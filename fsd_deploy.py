"""Compile and stage (then optionally apply) the Venator FSD changes.

`prepare` compiles the tables and stages payloads without touching the client.
`apply` installs them and records a rollback. Both refuse to run if the client's
baseline tables are not the ones the change sets were built against.

    python fsd_deploy.py prepare
    python fsd_deploy.py apply
    python fsd_deploy.py rollback
"""
import shutil
import sys
from pathlib import Path

import fsd_insert
from fsd_insert import KIT  # noqa: F401  (ensures sys.path is set)

from elysian_fsd.deployment import (          # noqa: E402
    apply_prepared_fsd_bundle,
    prepare_fsd_bundle,
    rollback_active_fsd_bundle,
    running_target_processes,
)

HERE = Path(__file__).resolve().parent
BUNDLE = HERE / "fsd_bundle"


def prepare():
    if BUNDLE.exists():
        shutil.rmtree(BUNDLE)
    project, profile = fsd_insert.main()
    bundle = prepare_fsd_bundle(profile, project, BUNDLE)
    print()
    print("STAGED to %s" % BUNDLE)
    for name in ("artifacts", "replacements", "manifest"):
        value = getattr(bundle, name, None)
        if value is None:
            continue
        try:
            print("  %-14s %d" % (name, len(value)))
        except TypeError:
            print("  %-14s %s" % (name, str(value)[:100]))
    return bundle, profile


def apply():
    bundle, profile = prepare()
    running = running_target_processes(profile.client_root, Path(r"C:\evejs\server"))
    if running:
        raise SystemExit("Close the EVE client first; running: %s" % (running,))
    apply_prepared_fsd_bundle(bundle, server_root=Path(r"C:\evejs\server"))
    print()
    print("APPLIED. Restart the client fully (a relog is not enough).")


def rollback():
    rollback_active_fsd_bundle()
    print("rolled back")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "prepare"
    {"prepare": prepare, "apply": apply, "rollback": rollback}[cmd]()
