"""Land everything that needs the EVE client closed, in the one safe order.

ORDER MATTERS, and getting it wrong is what silently lost the last build. The
FSD bundle snapshots resfileindex.txt when it is applied and restores that
snapshot on rollback - so any resource published BEFORE an apply/rollback cycle
is reverted by it. The corrected hull was published, then a rollback for the
dogma fix put the index back, and the client kept serving the older data.black
while reporting success. Resources therefore go LAST, after the FSD apply.

    python finish_deploy.py
"""
import json
import subprocess
import sys
from pathlib import Path

import install

HERE = Path(__file__).resolve().parent
PY = sys.executable
CONTAINER = "evejs-fresh-server-1"
AGGREGATE = "res:/dx9/model/spaceobjectfactory/data.black"


def run(*args, **kw):
    print("\n$ %s" % " ".join(str(a) for a in args))
    r = subprocess.run(args, cwd=str(HERE), **kw)
    if r.returncode:
        raise SystemExit("FAILED (%d): %s" % (r.returncode, " ".join(map(str, args))))


def client_running():
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
                        "(Get-Process exefile,eve_crashmon,evelauncher "
                        "-ErrorAction SilentlyContinue).Count"],
                       capture_output=True, text=True)
    return (r.stdout or "0").strip() not in ("", "0")


def main():
    if client_running():
        raise SystemExit("Close the EVE client (and its crash monitor) first.")

    # 1. back to pristine tables, so the compiler's per-table proofs match
    run(PY, "fsd_deploy.py", "rollback")
    # 2. one combined change set: graphicids + types + typedogma
    run(PY, "fsd_deploy.py", "apply")

    # 3. only now publish resources, so the apply cannot revert them
    hull = HERE / "native_out" / "data-with-venator.black"
    if not hull.is_file():
        raise SystemExit("missing %s - run the authoring pass first" % hull)
    install.publish(AGGREGATE, str(hull))

    request = json.loads((HERE / "loc_request.json").read_text("utf-8"))
    for entry in request["files"]:
        output = Path(entry["output"])
        if not output.is_file():
            raise SystemExit("missing %s - run Run-Loc.ps1 first" % output)
        install.publish(entry["logical"], str(output))

    # icons, at the folder graphicids now points at
    for icon in sorted((HERE / "icons").glob("900001_*")):
        install.publish("res:/elysian/ships/venator/icons/" + icon.name, str(icon))

    # 4. the server caches its static tables at boot - but ONLY needs restarting
    #    when server_patch.py has actually changed something. Restarting it drops
    #    a logged-in session ("server not responding" on undock), so it is opt-out.
    if "--no-server-restart" in sys.argv:
        print("\nskipping server restart (server tables unchanged)")
    else:
        run("docker", "restart", CONTAINER)

    print("\nDONE. Start the client fresh - a relog does not reload these.")


if __name__ == "__main__":
    main()
