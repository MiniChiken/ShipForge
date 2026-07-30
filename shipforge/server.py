"""ShipForge - a local editor for placing EVE ship hull data.

Standard library only, so there is nothing to install:

    python server.py [--port 8770] [--open]

Then open http://127.0.0.1:8770/

Long operations (a Blender probe, authoring inside the client, a deploy) run as
background jobs whose output the UI tails, because each takes tens of seconds.
"""
import argparse
import json
import mimetypes
import shutil
import subprocess
import threading
import traceback
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pipeline
import stats

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
PROJECTS = HERE / "projects"
PROJECTS.mkdir(exist_ok=True)

JOBS = {}
JOBS_LOCK = threading.Lock()


def blender_exe():
    found = shutil.which("blender")
    if found:
        return found
    candidates = sorted(Path(r"C:\Program Files\Blender Foundation").glob(
        "Blender */blender.exe"), reverse=True)
    if candidates:
        return str(candidates[0])
    raise RuntimeError("Blender not found; set it in the project or PATH")


def start_job(label, fn):
    job_id = uuid.uuid4().hex[:12]
    record = {"id": job_id, "label": label, "state": "running",
              "log": [], "result": None, "error": None}
    with JOBS_LOCK:
        JOBS[job_id] = record

    def run():
        try:
            record["result"] = fn(record["log"])
            record["state"] = "done"
        except Exception as exc:                     # surface it, do not swallow
            record["error"] = "%s\n%s" % (exc, traceback.format_exc())
            record["log"].append("FAILED: %s" % exc)
            record["state"] = "failed"

    threading.Thread(target=run, daemon=True).start()
    return record


def project_path(name):
    safe = "".join(c for c in name if c.isalnum() or c in "-_")
    if not safe:
        raise ValueError("bad project name")
    return PROJECTS / ("%s.json" % safe)


def default_project(name):
    return {
        "name": name,
        "hullName": "%s_t1" % name,
        "templateHull": "res:/dx9/model/spaceobjectfactory/hulls/ab2_t1.black",
        "resourceNamespace": "res:/elysian/ships/%s" % name,
        "category": "battleship",
        "targetLength": 1137.0,
        "model": "",
        # SOF DNA is <hull>:<faction>:<race>. The faction also decides which
        # MATERIALS the _m map's bands select, so it changes how bright the hull
        # renders - amarrbase band 1 is white_ivory_matt, minmatarbase band 1 is
        # black_gunmetal_brushed.
        "typeID": 900001,
        "sofFaction": "amarrbase",
        "sofRace": "amarr",
        "shield": {"centre": [0, 0, 0], "radius": [100, 100, 100], "sphere": 200},
        "turrets": [], "boosters": [], "navLights": [], "spotlights": [],
        "textures": {}, "dogma": {"hiSlots": 0},
        "serverContainer": "evejs-fresh-server-1",
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "ShipForge"

    def log_message(self, fmt, *args):
        pass                                   # the UI is the log

    # ------------------------------------------------------------ helpers
    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def send_file(self, path):
        if not path.is_file():
            self.send_error(404)
            return
        body = path.read_bytes()
        kind = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # --------------------------------------------------------------- GET
    def do_GET(self):
        route = self.path.split("?")[0]
        if route in ("/", "/index.html"):
            return self.send_file(STATIC / "index.html")
        if route.startswith("/static/"):
            return self.send_file(STATIC / route[len("/static/"):])
        if route == "/api/projects":
            # <name>.probe.json sits beside <name>.json; .stem would offer it as
            # a project called "<name>.probe"
            return self.send_json({"projects": sorted(
                p.stem for p in PROJECTS.glob("*.json")
                if not p.name.endswith(".probe.json"))})
        if route.startswith("/api/project/"):
            name = route[len("/api/project/"):]
            path = project_path(name)
            if not path.is_file():
                return self.send_json(default_project(name))
            return self.send_json(json.loads(path.read_text("utf-8")))
        if route.startswith("/api/probe/"):
            name = route[len("/api/probe/"):]
            path = PROJECTS / ("%s.probe.json" % name)
            if not path.is_file():
                return self.send_json({"error": "no probe yet"}, 404)
            return self.send_file(path)
        if route.startswith("/api/job/"):
            job_id = route[len("/api/job/"):]
            with JOBS_LOCK:
                record = JOBS.get(job_id)
            if record is None:
                return self.send_json({"error": "unknown job"}, 404)
            return self.send_json(record)
        if route == "/api/status":
            return self.send_json({"clientRunning": pipeline.client_running(),
                                   "referenceAvailable": stats.reference_available()})
        if route.startswith("/api/donor/"):
            return self.send_json(stats.donor_stats(route[len("/api/donor/"):]))
        if route.startswith("/api/donors"):
            query = ""
            if "?" in self.path:
                from urllib.parse import parse_qs
                query = (parse_qs(self.path.split("?", 1)[1]).get("q") or [""])[0]
            return self.send_json({"donors": stats.donor_candidates(query)})
        self.send_error(404)

    # -------------------------------------------------------------- POST
    def do_POST(self):
        route = self.path.split("?")[0]
        try:
            if route.startswith("/api/project/"):
                name = route[len("/api/project/"):]
                body = self.read_json()
                project_path(name).write_text(json.dumps(body, indent=1), "utf-8")
                return self.send_json({"saved": True,
                                       "problems": pipeline.validate(body)
                                                   + stats.validate_stats(body)})
            if route == "/api/import":
                return self.handle_import(self.read_json())
            if route == "/api/build":
                body = self.read_json()
                job = start_job("build", lambda log: pipeline.build(body, log))
                return self.send_json({"job": job["id"]})
            if route == "/api/deploy":
                body = self.read_json()
                # fsd may be "auto" (decide from the inputs), or a bool to force
                requested = body.get("fsd", "auto")
                fsd = requested if requested == "auto" else bool(requested)
                job = start_job("deploy", lambda log: pipeline.deploy(
                    body["project"], log, fsd=fsd,
                    restart_server=bool(body.get("restartServer", False))))
                return self.send_json({"job": job["id"]})
            if route == "/api/preview":
                body = self.read_json()
                job = start_job("preview", lambda log: pipeline.preview(
                    body.get("project", body), log,
                    width=int(body.get("width") or 1280),
                    height=int(body.get("height") or 820),
                    mode=body.get("mode") or "material"))
                return self.send_json({"job": job["id"]})
            if route == "/api/verify":
                body = self.read_json()
                job = start_job("verify", lambda log: pipeline.verify(body, log))
                return self.send_json({"job": job["id"]})
            if route == "/api/validate":
                body = self.read_json()
                return self.send_json({"problems":
                    pipeline.validate(body) + stats.validate_stats(body)})
            if route == "/api/snap":
                return self.handle_snap(self.read_json())
        except Exception as exc:
            return self.send_json({"error": str(exc),
                                   "trace": traceback.format_exc()}, 500)
        self.send_error(404)

    def handle_snap(self, body):
        """Exact raycast for specific points - the grid is too coarse to snap with."""
        model = body["model"]
        points = body["points"]
        if not Path(model).is_file():
            return self.send_json({"error": "no such file: %s" % model}, 400)
        request = HERE / "snap_request.json"
        result = HERE / "snap_result.json"
        request.write_text(json.dumps({
            "targetLength": float(body.get("targetLength") or 1137.0),
            "ignoreNamePrefix": body.get("ignoreNamePrefix") or "",
            "points": points}), "utf-8")
        if result.exists():
            result.unlink()

        def job(log):
            exe = blender_exe()
            args = [exe, "--background"]
            if model.lower().endswith(".blend"):
                args += [model, "--python", str(HERE / "blender_snap.py"),
                         "--", str(request), str(result)]
            else:
                args += ["--python", str(HERE / "blender_snap.py"),
                         "--", str(request), str(result), model]
            log.append("exact raycast of %d point(s)" % len(points))
            proc = subprocess.Popen(args, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True,
                                    errors="replace")
            for line in proc.stdout:
                line = line.rstrip()
                if line.startswith("  ("):
                    log.append(line)
            proc.wait()
            if not result.is_file():
                raise RuntimeError("snap produced no output (exit %d)" % proc.returncode)
            return json.loads(result.read_text("utf-8"))

        return self.send_json({"job": start_job("snap", job)["id"]})

    def handle_import(self, body):
        name = body["name"]
        model = body["model"]
        length = float(body.get("targetLength") or 1137.0)
        if not Path(model).is_file():
            return self.send_json({"error": "no such file: %s" % model}, 400)
        out = PROJECTS / ("%s.probe.json" % name)

        def job(log):
            exe = blender_exe()
            args = [exe, "--background"]
            if model.lower().endswith(".blend"):
                args += [model, "--python", str(HERE / "blender_probe.py"),
                         "--", str(out), str(length)]
            else:
                args += ["--python", str(HERE / "blender_probe.py"),
                         "--", str(out), str(length), model]
            log.append("$ " + " ".join(args))
            proc = subprocess.Popen(args, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True,
                                    errors="replace")
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    log.append(line)
            proc.wait()
            if not out.is_file():
                raise RuntimeError("probe produced no output (exit %d)" % proc.returncode)
            data = json.loads(out.read_text("utf-8"))
            return {"vertexCount": data["vertexCount"],
                    "bounds": data["bounds"],
                    "ellipsoid": data["ellipsoid"],
                    "materials": data["materials"],
                    "nozzles": len(data["nozzles"])}

        return self.send_json({"job": start_job("import", job)["id"]})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()
    url = "http://127.0.0.1:%d/" % args.port
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print("ShipForge on %s   (tools: %s)" % (url, pipeline.TOOLS))
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
