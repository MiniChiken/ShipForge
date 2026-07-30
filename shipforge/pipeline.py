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
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
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
    """True if an EVE client (or its crash monitor) is up.

    Fails SAFE: if the check itself cannot answer, report "running". Treating an
    unanswered check as "closed" let a deploy start, roll the FSD bundle back,
    and only then hit the suite's own client check - leaving the tables pristine
    and the ship's typeID gone.
    """
    probe = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-Process exefile,eve_crashmon,evelauncher "
         "-ErrorAction SilentlyContinue).Count"],
        capture_output=True, text=True)
    if probe.returncode != 0:
        return True
    text = (probe.stdout or "").strip()
    if not text.isdigit():
        return True
    return int(text) > 0


FSD_FIELDS = ("typeID", "graphicID", "hullName", "sofFaction", "sofRace",
              "iconFolder", "dogma", "displayName", "radius",
              # stats and hull bonuses land in typedogma, so they are FSD too
              "donorTypeID", "donorGraphicID", "dogmaAttributes", "dogmaEffects")


def fsd_fingerprint(project):
    """Hash of everything that decides the CLIENT'S STATIC TABLES.

    Includes fsd_insert.py's source, because that module - not the project -
    holds the donor typeIDs and the slot/tank values it patches, so editing it
    is a real FSD change even when the project is untouched.
    """
    payload = {k: project.get(k) for k in FSD_FIELDS}
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    source = TOOLS / "fsd_insert.py"
    if source.is_file():
        digest.update(source.read_bytes())
    return digest.hexdigest()


def fsd_stamp_path(project):
    return TOOLS / "native_out" / ("%s.fsdstamp.json" % project["hullName"])


def fsd_is_current(project):
    """(is_current, reason) for the applied FSD bundle versus this project."""
    stamp = fsd_stamp_path(project)
    if not stamp.is_file():
        return False, "no FSD bundle has been applied by ShipForge yet"
    try:
        recorded = json.loads(stamp.read_text("utf-8")).get("fingerprint")
    except (OSError, ValueError):
        return False, "the FSD stamp is unreadable"
    if recorded != fsd_fingerprint(project):
        return False, "the FSD inputs changed since the last apply"
    if live_type_missing(project, []):
        return False, "the typeID is missing from the live tables"
    return True, "up to date"


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


def request_fingerprint(request):
    """Stable hash of an authoring request, ignoring key order."""
    return hashlib.sha256(
        json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def build_stamp_path(project):
    return TOOLS / "native_out" / ("%s.buildstamp.json" % project["hullName"])


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

    # Record WHAT this artifact was built from. Deploy publishes a file from
    # disk, and without this there is nothing tying that file to the project
    # being deployed - edit, skip Build, hit Deploy, and a stale hull ships
    # while every step reports success.
    fingerprint = request_fingerprint(request)
    build_stamp_path(project).write_text(json.dumps({
        "fingerprint": fingerprint,
        "hullName": project["hullName"],
        "authoredAt": result.get("authored", {}).get("name") and time.strftime(
            "%Y-%m-%dT%H:%M:%S"),
        "turretLocators": result.get("turretLocators"),
        "boosterItems": result.get("boosterItems"),
    }, indent=1), "utf-8")
    _log(sink, "build fingerprint %s" % fingerprint[:16])
    return {"problems": problems, "result": result, "fingerprint": fingerprint}


def build_is_current(project):
    """(is_current, reason) for the artifact on disk versus this project."""
    hull_black = TOOLS / "native_out" / ("data-with-%s.black" % project["hullName"])
    if not hull_black.is_file():
        return False, "no hull has been built yet"
    stamp = build_stamp_path(project)
    if not stamp.is_file():
        return False, "the built hull has no build stamp (built before stamping)"
    try:
        recorded = json.loads(stamp.read_text("utf-8")).get("fingerprint")
    except (OSError, ValueError):
        return False, "the build stamp is unreadable"
    want = request_fingerprint(
        authoring_request(project, str((TOOLS / "native_out")).replace("\\", "/")))
    if recorded != want:
        return False, ("the built hull was made from different data "
                       "(stamp %s, project %s)" % (recorded[:12], want[:12]))
    return True, "up to date"


def publish(sink, res_path, local):
    _run(sink, [PY, TOOLS / "install.py", "--publish", res_path, local])


def deploy(project, sink, fsd="auto", restart_server=False):
    """Push to the live client, in the only safe order.

    fsd="auto" (the default) touches the client's static tables ONLY when their
    inputs actually changed. That matters because an apply is a rollback followed
    by a multi-minute compile: if anything fails in between, the tables are left
    pristine, the ship's typeID does not exist, and the client dies at character
    select. A placement change has no business taking that risk, and previously
    every deploy did.
    """
    if fsd == "auto":
        current, reason = fsd_is_current(project)
        fsd = not current
        _log(sink, "FSD %s (%s)"
             % ("needs applying" if fsd else "unchanged, skipping", reason))
    # Only the FSD apply needs the client closed - it rewrites files the client
    # holds open. Publishing a resource just writes a blob and one index line,
    # which a running client neither reads nor locks (it read the index at
    # startup), so pure placement changes can be deployed live and picked up on
    # the next restart. That keeps the edit-look-adjust loop short.
    if fsd and client_running():
        raise RuntimeError(
            "Close the EVE client first - the FSD apply cannot rewrite files "
            "that are open, and the client only reads the index at startup.")
    if not fsd:
        _log(sink, "resource-only deploy (no FSD changes); a running client is "
                   "fine but must be restarted to see this")

    # Never publish an artifact that was not built from THIS project. Deploy
    # takes a file off disk, so without this an edit that skipped Build shipped
    # the previous hull while every step reported success.
    current, reason = build_is_current(project)
    if not current:
        _log(sink, "hull is stale (%s) - building it now" % reason)
        build(project, sink)
        current, reason = build_is_current(project)
        if not current:
            raise RuntimeError("could not produce a current hull: %s" % reason)
    else:
        _log(sink, "hull build is current")

    if fsd:
        # Rollback first: the compiler's per-table proofs are bound to the
        # pristine table hashes, so a second bundle on top is refused. But a
        # bundle may already be rolled back - the suite reports that as
        # "No active Elysian bundle owns this target", which its own operation
        # lock then re-raises as a misleading TargetBusyError because
        # FileNotFoundError is an OSError. Not having a bundle to roll back is
        # a fine state to apply from, so do not fail the deploy over it.
        try:
            _run(sink, [PY, TOOLS / "fsd_deploy.py", "rollback"])
        except RuntimeError:
            _log(sink, "nothing to roll back (no active bundle) - continuing")
        # A rollback that succeeds followed by an apply that fails is WORSE than
        # doing nothing: the ship's typeID is gone from the client's tables and
        # the only symptom is a broken login. Say so unmistakably.
        try:
            _run(sink, [PY, TOOLS / "fsd_deploy.py", "apply"])
        except RuntimeError as exc:
            # The tables are pristine at this point, which is exactly the state
            # a fresh apply needs, so one retry is worth attempting before
            # leaving the client unable to log in.
            _log(sink, "apply failed (%s) - retrying once, because the tables "
                       "are now pristine and that is what apply needs" % exc)
            try:
                _run(sink, [PY, TOOLS / "fsd_deploy.py", "apply"])
            except RuntimeError as retry_exc:
                raise RuntimeError(
                    "FSD APPLY FAILED TWICE AFTER A SUCCESSFUL ROLLBACK. The "
                    "client's tables are PRISTINE, so typeID %s does not exist "
                    "and character select will fail with TypeNotFoundException. "
                    "Recover with: python fsd_deploy.py apply   (then republish "
                    "resources). Underlying error: %s"
                    % (project.get("typeID", 900001), retry_exc))
        fsd_stamp_path(project).write_text(json.dumps({
            "fingerprint": fsd_fingerprint(project),
            "appliedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }, indent=1), "utf-8")

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

    # Always confirm the typeID is really in the LIVE tables before claiming
    # success. A bundle that has been rolled back leaves the ship's typeID
    # absent, and the only symptom is the client throwing
    # TypeNotFoundException at character select - which looks like a broken
    # login, not a failed deploy. Cheap check, caught exactly this once.
    missing = live_type_missing(project, sink)
    if missing:
        raise RuntimeError(
            "DEPLOY INCOMPLETE: typeID %s is absent from %s in the live client "
            "tables. The client will fail at character select with "
            "TypeNotFoundException. Re-run the deploy."
            % (project.get("typeID", 900001), ", ".join(missing)))

    _log(sink, "DONE - start the client fresh; a relog does not reload resources")


def live_type_missing(project, sink):
    """Which of the client's FSD tables are missing this project's typeID.

    Reads the tables the live resfileindex currently points at, so it reflects
    what the client will actually load rather than what we intended to write.
    """
    type_id = int(project.get("typeID", 900001))
    index = CLIENT_TQ / "resfileindex.txt"
    rows = {}
    with index.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.rstrip("\n").split(",")
            if len(parts) >= 2:
                rows[parts[0].lower()] = parts[1]

    missing = []
    try:
        sys.path.insert(0, str(TOOLS))
        import verify_fsd                                  # noqa: E402
        _run(sink, [PY, TOOLS / "verify_fsd.py", "tasks"])
        _run(sink, ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", str(TOOLS / "Run-Fsd-Verify.ps1")])
        for table in ("types", "graphicids", "typedogma"):
            path = TOOLS / "fsd_verify" / ("%s.jsonl" % table)
            if not path.is_file():
                missing.append(table + " (not exported)")
                continue
            found = False
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    record = json.loads(line)
                    if record.get("key", record.get("_key")) == type_id:
                        found = True
                        break
            _log(sink, "live %-11s typeID %d present: %s" % (table, type_id, found))
            if not found:
                missing.append(table)
    except Exception as exc:
        _log(sink, "could not verify live tables (%s) - check manually with "
                   "verify_fsd.py" % exc)
    return missing


VIEWER = Path(os.environ.get("SHIPFORGE_VIEWER", r"C:\evejs\tools\trinity-viewer"))
# Slow enough to read placement off a moving hull. Override per project with
# "previewRotationSpeed"; the viewer clamps to 0.0-3.0.
DEFAULT_PREVIEW_ROTATION = 0.05


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


def preview_backup_path(project):
    return TOOLS / "native_out" / ("%s.previewbackup.json" % project["hullName"])


def _index_row(resource_path):
    """The whole current index line for a logical path, or None."""
    index = CLIENT_TQ / "resfileindex.txt"
    target = resource_path.lower()
    with index.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            row = line.rstrip("\n")
            if row.split(",")[0].lower() == target:
                return row
    return None


def revert_preview(project, sink):
    """Put the index row back the way it was before the last Preview.

    Blobs are never deleted - a publish writes a NEW blob under a new md5 - so
    restoring is just rewriting one line, and the previewed hull stays on disk if
    you want it again.
    """
    backup = preview_backup_path(project)
    if not backup.is_file():
        raise RuntimeError("no preview to revert (no snapshot recorded)")
    saved = json.loads(backup.read_text("utf-8"))
    row, resource = saved["row"], saved["resource"]

    index = CLIENT_TQ / "resfileindex.txt"
    lines = index.read_text(encoding="utf-8", errors="replace").splitlines()
    target = resource.lower()
    for position, line in enumerate(lines):
        if line.split(",")[0].lower() == target:
            if line == row:
                _log(sink, "index row already matches the snapshot - nothing to do")
                return {"reverted": False}
            lines[position] = row
            index.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
            _log(sink, "restored %s to its pre-preview blob" % resource)
            _log(sink, "  %s" % row.split(",")[1])
            backup.unlink()
            return {"reverted": True, "resource": resource}
    raise RuntimeError("%s is not in the index any more" % resource)


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

    # Build first if the artifact does not match the project. Without this,
    # Preview published whatever hull happened to be on disk, so an edit made
    # since the last Build simply did not appear - which looks like Preview not
    # working rather than Preview showing an older ship. Same guard as Deploy.
    current, reason = build_is_current(project)
    if not current:
        _log(sink, "hull is stale (%s) - building it now" % reason)
        build(project, sink)
        current, reason = build_is_current(project)
        if not current:
            raise RuntimeError("could not produce a current hull: %s" % reason)
    else:
        _log(sink, "hull build is current")

    # Snapshot the index row we are about to overwrite so Preview can be undone.
    # Trinity resolves a hull through the client's resource system, so a preview
    # has to publish data.black - but nothing says it has to STAY published.
    snapshot = _index_row(AGGREGATE)
    if snapshot:
        preview_backup_path(project).write_text(json.dumps(
            {"resource": AGGREGATE, "row": snapshot,
             "takenAt": time.strftime("%Y-%m-%dT%H:%M:%S")}, indent=1), "utf-8")

    hull_black = TOOLS / "native_out" / ("data-with-%s.black" % project["hullName"])
    publish(sink, AGGREGATE, str(hull_black))

    catalog = _project_catalog(project, sink)
    commands = VIEWER / "runtime" / "commands"
    commands.mkdir(parents=True, exist_ok=True)
    command_path = commands / ("shipforge-%s.jsonl" % project["hullName"])
    command_path.write_text("", "ascii")
    rotation = project.get("previewRotationSpeed", DEFAULT_PREVIEW_ROTATION)

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

    # The viewer defaults to 1.0x, which spins a 1137m hull too fast to judge
    # placement against. It polls its command file from offset 0, so a line
    # written BEFORE launch is consumed during startup - before the control
    # panel exists - and creating the slider then resets the value from its own
    # default. Send it once the window is up instead. Done on a thread so the
    # preview call still returns immediately.
    def _set_rotation():
        time.sleep(12)
        with command_path.open("a") as fh:
            fh.write(json.dumps({"command": "rotationspeed",
                                 "value": rotation}) + "\n")

    threading.Thread(target=_set_rotation, daemon=True).start()
    _log(sink, "rotation speed will be set to %gx once the viewer is up" % rotation)
    _log(sink, "viewer launched. Left-drag orbits, right-drag pans, wheel zooms, "
               "right-click toggles its panel, Esc closes it.")
    return {"dna": dna, "radius": radius, "published": AGGREGATE}


# --------------------------------------------------------------- vanilla ----
def owned_custom_ships(project):
    """Server items that reference this project's typeID.

    Going vanilla strips the typeID from the client's tables, so anything still
    referencing it points at a type that no longer exists - which is what breaks
    a client at character select. The authoritative source is the items table in
    gamestore.sqlite: characters/data.json carries a shipTypeID too, but it LAGS
    (it read Capsule 670 while the sqlite items table already held the custom
    ship), so trusting it would miss exactly the case this guards.
    """
    type_id = int(project.get("typeID", 900001))
    container = project.get("serverContainer", "evejs-fresh-server-1")
    local = HERE / "srv_gamestore_check.sqlite"
    copied = subprocess.run(
        ["docker", "cp",
         "%s:/var/lib/evejs/gameStore/gamestore.sqlite" % container, str(local)],
        capture_output=True, text=True)
    if copied.returncode:
        raise RuntimeError("could not read the server's gamestore: %s"
                           % (copied.stderr or "").strip())

    import sqlite3
    found = []
    connection = sqlite3.connect("file:%s?mode=ro" % local.as_posix(), uri=True)
    try:
        for key, blob in connection.execute("select key, json from items"):
            try:
                value = json.loads(blob)
            except ValueError:
                continue
            stack = [value]
            while stack:
                node = stack.pop()
                if isinstance(node, dict):
                    if node.get("typeID") == type_id:
                        found.append({"itemID": node.get("itemID", key),
                                      "ownerID": node.get("ownerID"),
                                      "locationID": node.get("locationID"),
                                      "itemName": node.get("itemName")})
                    stack.extend(node.values())
                elif isinstance(node, list):
                    stack.extend(node)
    finally:
        connection.close()
        local.unlink(missing_ok=True)
    return found


def vanilla_blockers(project):
    """Reasons NOT to strip the custom ship right now."""
    problems = []
    if client_running():
        problems.append(
            "the EVE client is running - close it. Live state cannot be read "
            "reliably while it is up, and the FSD rollback cannot rewrite files "
            "the client holds open.")
    try:
        owned = owned_custom_ships(project)
    except RuntimeError as exc:
        problems.append("%s (cannot confirm nobody owns the ship)" % exc)
        return problems
    for item in owned:
        problems.append(
            "character %s still has %s (itemID %s) at location %s. Going vanilla "
            "removes typeID %s, so that item would reference a type the client "
            "cannot resolve and character select would fail. Board another ship "
            "and trash or repackage it first."
            % (item["ownerID"], item.get("itemName") or "the custom ship",
               item["itemID"], item["locationID"], project.get("typeID", 900001)))
    return problems


def go_vanilla(project, sink, force=False):
    """Return the client and server to stock, keeping the work re-enableable.

    Nothing is destroyed. install.py --revert restores the resfileindex to the
    backup taken before the first publish, and publishing NEVER deletes a blob -
    every custom resource stays on disk under its own md5. The project, the built
    hull and the FSD bundle all remain, so Deploy puts it all back.
    """
    blockers = vanilla_blockers(project)
    for problem in blockers:
        _log(sink, "BLOCKER: %s" % problem)
    if blockers and not force:
        raise RuntimeError(
            "refusing to go vanilla: %d blocker(s) above. Resolve them, or pass "
            "force to override - overriding while the ship is owned WILL break "
            "the client at character select." % len(blockers))
    if blockers:
        _log(sink, "FORCED past %d blocker(s)" % len(blockers))

    try:
        _run(sink, [PY, TOOLS / "fsd_deploy.py", "rollback"])
    except RuntimeError:
        _log(sink, "no active FSD bundle - already stock")
    # restores every stock resource we ever republished, in one step
    _run(sink, [PY, TOOLS / "install.py", "--revert"])
    _run(sink, [PY, TOOLS / "server_patch.py", "revert"])
    _run(sink, ["docker", "restart",
                project.get("serverContainer", "evejs-fresh-server-1")])

    missing = live_type_missing(project, sink)
    state = {
        "disabledAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "typeID": project.get("typeID"),
        "hullName": project.get("hullName"),
        "tablesCleared": missing,
        "reEnable": "ShipForge Deploy, or python finish_deploy.py",
    }
    vanilla_state_path(project).write_text(json.dumps(state, indent=1), "utf-8")
    if len(missing) != 3:
        _log(sink, "WARNING: typeID still present in %s"
             % ", ".join(t for t in ("types", "graphicids", "typedogma")
                         if t not in missing))
    _log(sink, "VANILLA. Nothing was deleted - Deploy restores the ship. "
               "Start the client fresh.")
    return state


def vanilla_state_path(project):
    return TOOLS / "native_out" / ("%s.vanilla.json" % project["hullName"])


def is_vanilla(project):
    return vanilla_state_path(project).is_file()


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
