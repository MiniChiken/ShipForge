"""Turn a ShipForge project into a live ship.

Deliberately reuses the workers that are already proven rather than
reimplementing them: author_venator.py for native SOF authoring, install.py for
publishing, fsd_deploy.py / finish_deploy.py for the client's static data.

The rules encoded here are the ones that cost real debugging time:

  * an FSD apply or rollback rewrites the WHOLE resfileindex, so every resource
    publish must come AFTER the apply or it is silently reverted
  * hiSlots must equal the number of turret locator GROUPS, because the client
    maps a fitted turret to locator_turret_<high slot index + 1>
  * restarting the server drops a logged-in session, so it is opt-in
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# the authoring workers live in the repo root, one level up
TOOLS = Path(os.environ.get("SHIPFORGE_TOOLS", str(HERE.parent)))
CLIENT_TQ = Path(r"C:\EVE-EVEJS\client\EVE\tq")
KIT = TOOLS / "kit" / "EVE-New-Ship-Native-Authoring-Kit-build3396210"
RESFILES = Path(r"C:\EVE-EVEJS\client\EVE\ResFiles")
PY = sys.executable
AGGREGATE = "res:/dx9/model/spaceobjectfactory/data.black"


def _log(sink, message):
    sink.append(message)
    print(message, flush=True)


def _run(sink, args, cwd=None, env=None):
    _log(sink, "$ " + " ".join(str(a) for a in args))
    proc = subprocess.Popen(
        [str(a) for a in args], cwd=str(cwd or TOOLS),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, errors="replace", env=env)
    for line in proc.stdout:
        _log(sink, line.rstrip())
    proc.wait()
    if proc.returncode:
        raise RuntimeError("exit %d: %s" % (proc.returncode, args[0]))


def client_running():
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-Process exefile,eve_crashmon,evelauncher "
         "-ErrorAction SilentlyContinue).Count"],
        capture_output=True, text=True).stdout
    return (out or "0").strip() not in ("", "0")


def turret_groups(project):
    """Distinct hardpoint groups - the DIGITS in each locator name."""
    groups = set()
    for t in project.get("turrets", []):
        digits = "".join(c for c in t.get("name", "") if c.isdigit())
        if digits:
            groups.add(digits)
    return sorted(groups)


def validate(project):
    """Problems worth refusing to build over, each learned the hard way."""
    problems = []
    groups = turret_groups(project)
    hi = project.get("dogma", {}).get("hiSlots")
    if groups and hi is not None and int(hi) != len(groups):
        problems.append(
            "hiSlots is %s but the hull has %d turret locator groups (%s). "
            "A turret fitted in a high slot with no matching group renders "
            "nothing." % (hi, len(groups), ", ".join(groups)))
    for t in project.get("turrets", []):
        n = t.get("normal") or [0, 1, 0]
        if abs(n[0]) < 1e-4 and abs(n[2]) < 1e-4:
            continue          # straight up is legitimate for a centreline mount
    for b in project.get("boosters", []):
        scale = b.get("scale") or []
        if len(scale) == 3 and scale[0] > 0:
            ratio = scale[2] / scale[0]
            if ratio < 8 or ratio > 20:
                problems.append(
                    "booster at %s has a plume Z:XY ratio of %.1f; stock hulls "
                    "run about 14 (10-18)." % (b.get("pos"), ratio))
    shield = project.get("shield") or {}
    if shield.get("radius") and shield.get("halfExtent"):
        for axis, (r, h) in enumerate(zip(shield["radius"], shield["halfExtent"])):
            if r < h:
                problems.append(
                    "shield radius axis %d (%.1f) is smaller than the hull's "
                    "half-extent (%.1f)." % (axis, r, h))
    return problems


def authoring_request(project, out_dir):
    ns = project["resourceNamespace"].rstrip("/")
    hull = project["hullName"]
    shield = project.get("shield", {})
    return {
        "templateHullResource": project["templateHull"],
        "aggregateResource": AGGREGATE,
        "outputHullBlack": "%s/%s.black" % (out_dir, hull),
        "outputAggregateBlack": "%s/data-with-%s.black" % (out_dir, hull),
        "scalars": {
            "name": hull,
            "description": project.get("sofDescription", "ship/%s" % hull),
            "category": project.get("category", "battleship"),
            "geometryResFilePath": "%s/%s.gr2" % (ns, hull),
            "isSkinned": False,
            "boundingSphere": list(shield.get("centre", [0, 0, 0])) + [
                shield.get("sphere", 500.0)],
            "shapeEllipsoidCenter": list(shield.get("centre", [0, 0, 0])),
            "shapeEllipsoidRadius": list(shield.get("radius", [100, 100, 100])),
        },
        "textures": project.get("textures", {}),
        "boosters": project.get("boosters", []),
        "turrets": project.get("turrets", []),
        "navLights": project.get("navLights", []),
        "spotlights": project.get("spotlights", []),
    }


def _client_env():
    env = dict(os.environ)
    env["PYTHONHOME"] = str(KIT / "runtime" / "python27")
    env["PYTHONPATH"] = str(KIT / "runtime" / "python27" / "Lib")
    env["ELYSIAN_SHIPKIT_RESFILES"] = str(RESFILES)
    return env


def run_in_client(sink, worker, *args):
    """exefile.exe /py <worker> ... - the client's own interpreter and loaders."""
    exe = CLIENT_TQ / "bin64" / "exefile.exe"
    _run(sink, [exe, "/py", TOOLS / worker] + list(args) + ["/inherit"],
         cwd=CLIENT_TQ, env=_client_env())


def build(project, sink):
    """Author the SOF hull. Does not touch the live client."""
    problems = validate(project)
    for p in problems:
        _log(sink, "WARNING: " + p)

    out_dir = TOOLS / "native_out"
    out_dir.mkdir(exist_ok=True)
    request = authoring_request(project, str(out_dir).replace("\\", "/"))
    request_path = HERE / "shipforge_request.json"
    request_path.write_text(json.dumps(request, indent=1), "utf-8")
    _log(sink, "wrote %s" % request_path)

    result_path = HERE / "shipforge_author_result.json"
    if result_path.exists():
        result_path.unlink()
    run_in_client(sink, "author_venator.py", result_path, request_path)

    if not result_path.exists():
        raise RuntimeError("authoring produced no result file")
    result = json.loads(result_path.read_text("utf-8"))
    if not result.get("success"):
        raise RuntimeError(result.get("error", "authoring failed"))
    _log(sink, "authored: %d boosters, %d turret locators, %d nav lights, "
               "%d spotlights"
         % (result.get("boosterItems", 0), result.get("turretLocators", 0),
            result.get("navLights", 0), result.get("spotlights", 0)))
    return {"problems": problems, "result": result}


def publish(sink, res_path, local):
    _run(sink, [PY, TOOLS / "install.py", "--publish", res_path, local])


def deploy(project, sink, fsd=True, restart_server=False):
    """Push to the live client, in the only safe order."""
    if client_running():
        raise RuntimeError(
            "Close the EVE client first - the FSD apply cannot rewrite files "
            "that are open, and the client only reads the index at startup.")

    if fsd:
        # rollback first: the compiler's per-table proofs are bound to the
        # pristine table hashes, so a second bundle on top is refused
        _run(sink, [PY, TOOLS / "fsd_deploy.py", "rollback"])
        _run(sink, [PY, TOOLS / "fsd_deploy.py", "apply"])

    # resources LAST - an apply/rollback rewrites the whole index
    hull_black = TOOLS / "native_out" / ("data-with-%s.black" % project["hullName"])
    if hull_black.exists():
        publish(sink, AGGREGATE, str(hull_black))
    for res_path, local in (project.get("extraResources") or []):
        publish(sink, res_path, local)

    if restart_server:
        _run(sink, ["docker", "restart",
                    project.get("serverContainer", "evejs-fresh-server-1")])
    else:
        _log(sink, "server not restarted (its tables were unchanged)")

    _log(sink, "DONE - start the client fresh; a relog does not reload resources")


VIEWER = Path(os.environ.get("SHIPFORGE_VIEWER", r"C:\evejs\tools\trinity-viewer"))


def project_dna(project):
    """SOF DNA is <hull>:<faction>:<race>, per the viewer's own catalogue."""
    return "%s:%s:%s" % (project["hullName"],
                         project.get("sofFaction", "amarrbase"),
                         project.get("sofRace", "amarr"))


def _base_catalog(sink):
    """Jessica ships its metadata catalogue gzipped; restore it once."""
    runtime = VIEWER / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    catalog = runtime / "catalog.json"
    if catalog.is_file() and catalog.stat().st_size > 0:
        return catalog
    packed = VIEWER / "catalog" / "catalog.json.gz"
    if not packed.is_file():
        return None
    import gzip
    _log(sink, "restoring viewer catalogue from %s" % packed.name)
    with gzip.open(packed, "rb") as src, open(catalog, "wb") as dst:
        shutil.copyfileobj(src, dst)
    return catalog


def _project_catalog(project, sink):
    """A catalogue copy containing OUR ship, written beside the viewer's own.

    The DNA passed on the command line is not authoritative. The viewer does:

        self.catalog_index = self.find_catalog_index(self.type_id)
        ...
        if self.current_asset:
            self.dna = current_asset.get("dna") or self.dna

    and find_catalog_index falls back to `0` when the typeID is absent - so an
    unknown typeID silently selects the FIRST catalogue asset and overwrites the
    DNA, which is why previewing showed an Abaddon. Injecting an entry for our
    typeID makes the viewer resolve our ship and keeps its nebula, SKIN and
    weapon features working.
    """
    base = _base_catalog(sink)
    if not base:
        return None
    payload = json.loads(base.read_text("utf-8"))
    assets = payload.get("assets")
    if not isinstance(assets, list):
        return base

    type_id = int(project.get("typeID", 900001))
    entry = {
        "typeID": type_id,
        "name": project.get("displayName") or project["name"].title(),
        "groupID": 27, "groupName": "Battleship", "categoryID": 6,
        "graphicID": project.get("graphicID", type_id),
        "radius": project.get("shield", {}).get("sphere") or 500,
        "published": True,
        "sourceKind": "shipTypes", "assetKind": "ship",
        "sof": {"hull": project["hullName"],
                "faction": project.get("sofFaction", "amarrbase"),
                "race": project.get("sofRace", "amarr")},
        "dna": project_dna(project),
    }
    payload["assets"] = [a for a in assets
                         if int(a.get("typeID") or 0) != type_id] + [entry]
    payload["selectedTypeID"] = type_id

    out = VIEWER / "runtime" / ("catalog-shipforge-%s.json" % project["name"])
    out.write_text(json.dumps(payload), "utf-8")
    _log(sink, "catalogue: injected typeID %d as %r among %d assets -> %s"
         % (type_id, entry["dna"], len(payload["assets"]), out.name))
    return out


def preview(project, sink, width=1280, height=820, mode="material"):
    """Render the authored hull in the native Trinity viewer.

    Trinity resolves a hull through the client's resource system, so the hull has
    to be reachable at res:/dx9/model/spaceobjectfactory/data.black. This
    therefore publishes THAT ONE RESOURCE - it does not touch the FSD tables, the
    server, or the ship's type and dogma, and install.py keeps the index backup.

    The viewer is a separate exefile instance, so this is safe with the game
    running; the viewer only sees what the index said when it started.
    """
    viewer_script = VIEWER / "trinity_live_viewer.py"
    if not viewer_script.is_file():
        raise RuntimeError(
            "Trinity viewer not found at %s. Clone "
            "https://github.com/JohnElysian/Eve-Online-Trinity-Viewer there, or "
            "set SHIPFORGE_VIEWER." % VIEWER)

    hull_black = TOOLS / "native_out" / ("data-with-%s.black" % project["hullName"])
    if not hull_black.is_file():
        raise RuntimeError("build the hull first - %s does not exist" % hull_black)
    publish(sink, AGGREGATE, str(hull_black))

    catalog = _project_catalog(project, sink)
    commands = VIEWER / "runtime" / "commands"
    commands.mkdir(parents=True, exist_ok=True)
    command_path = commands / ("shipforge-%s.jsonl" % project["hullName"])
    command_path.write_text("", "ascii")

    dna = project_dna(project)
    radius = project.get("shield", {}).get("sphere") or 500
    args = [str(CLIENT_TQ / "bin64" / "exefile.exe"), "/py", str(viewer_script),
            str(project.get("typeID", 900001)), dna, str(radius),
            str(width), str(height), mode]
    if catalog:
        args += [str(catalog), str(command_path)]
    args += ["/inherit"]

    env = _client_env()
    # Jessica looks for its own ResFiles variable
    env["ELYSIAN_JESSICA_RESFILES"] = str(RESFILES)

    _log(sink, "DNA %s   radius %s" % (dna, radius))
    _log(sink, "$ " + " ".join(args))
    # detached: the viewer is an interactive window, not a batch step
    subprocess.Popen(args, cwd=str(CLIENT_TQ), env=env)
    _log(sink, "viewer launched. Left-drag orbits, right-drag pans, wheel zooms, "
               "right-click toggles its panel, Esc closes it.")
    return {"dna": dna, "radius": radius, "published": AGGREGATE}


def verify(project, sink):
    """Read the hull back out of the PUBLISHED data.black, not the file we wrote."""
    request = {"aggregateResource": AGGREGATE, "hullName": project["hullName"]}
    request_path = HERE / "shipforge_probe_request.json"
    request_path.write_text(json.dumps(request, indent=1), "utf-8")
    result_path = HERE / "shipforge_probe_result.json"
    if result_path.exists():
        result_path.unlink()
    run_in_client(sink, "probe_hull.py", result_path, request_path)
    if not result_path.exists():
        raise RuntimeError("probe produced no result")
    live = json.loads(result_path.read_text("utf-8"))
    if not live.get("success"):
        raise RuntimeError(live.get("error", "probe failed"))

    checks = []

    def check(label, got, want, tol=0.05):
        ok = (got is not None and want is not None
              and all(abs(a - b) <= tol for a, b in zip(got, want)))
        checks.append({"label": label, "ok": bool(ok),
                       "got": got, "want": want})

    shield = project.get("shield", {})
    check("shapeEllipsoidRadius", live["hull"].get("shapeEllipsoidRadius"),
          list(shield.get("radius", [])))
    check("shapeEllipsoidCenter", live["hull"].get("shapeEllipsoidCenter"),
          list(shield.get("centre", [])))
    checks.append({"label": "turret locators",
                   "ok": len(live.get("turrets", [])) == len(project.get("turrets", [])),
                   "got": len(live.get("turrets", [])),
                   "want": len(project.get("turrets", []))})
    checks.append({"label": "boosters",
                   "ok": len(live.get("boosters", [])) == len(project.get("boosters", [])),
                   "got": len(live.get("boosters", [])),
                   "want": len(project.get("boosters", []))})
    groups = turret_groups(project)
    live_groups = sorted({"".join(c for c in t["name"] if c.isdigit())
                          for t in live.get("turrets", [])})
    checks.append({"label": "turret groups match hiSlots",
                   "ok": live_groups == groups, "got": live_groups, "want": groups})
    for c in checks:
        _log(sink, "%-26s %s  got=%s want=%s"
             % (c["label"], "OK" if c["ok"] else "MISMATCH", c["got"], c["want"]))
    return {"checks": checks, "live": live}
