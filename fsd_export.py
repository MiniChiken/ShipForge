"""Export FSD tables to JSONL using the kit's worker, run inside the EVE client.

The kit's exporter shells out to a standalone python27.exe, but the bundled
runtime is stdlib-only (Lib, no interpreter) - it is meant to be PYTHONHOME for
the client's own interpreter. The worker also needs the client's *Loader.pyd
modules, so running it inside exefile.exe /py is both necessary and simpler.

Prepares worker.py + task.json here; Run-Fsd-Export.ps1 does the invocation.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "kit", "EVE-New-Ship-Native-Authoring-Kit-build3396210", "fsd-reference"))

from elysian_fsd.native_export import WORKER_SOURCE  # noqa: E402

import resfile  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "fsd_export")
WORK = os.path.join(HERE, "fsd_work")

TABLES = {
    "graphicids": ("graphicIDsLoader", "res:/staticdata/graphicids.fsdbinary"),
    "types": ("typesLoader", "res:/staticdata/types.fsdbinary"),
    "typedogma": ("typeDogmaLoader", "res:/staticdata/typedogma.fsdbinary"),
}


def main():
    for d in (OUT, WORK):
        if not os.path.isdir(d):
            os.makedirs(d)
    worker = os.path.join(WORK, "worker.py")
    with open(worker, "w", encoding="utf-8") as fh:
        fh.write(WORKER_SOURCE)
    print("worker -> %s (%d bytes)" % (worker, os.path.getsize(worker)))

    tasks = []
    for name, (loader, respath) in sorted(TABLES.items()):
        blob = resfile.blob_path(respath)
        task = os.path.join(WORK, "task-%s.json" % name)
        with open(task, "w", encoding="utf-8") as fh:
            json.dump({
                "tableName": name,
                "loaderModule": loader,
                "resourcePath": blob,
                "outputPath": os.path.join(OUT, "%s.jsonl" % name),
                "rootValueProjection": False,
                "singletonObjectRoot": False,
            }, fh)
        tasks.append((name, task, os.path.join(WORK, "result-%s.json" % name)))
        print("  %-12s loader=%-18s blob=%s" % (name, loader, os.path.basename(blob)))
    with open(os.path.join(WORK, "tasks.json"), "w", encoding="utf-8") as fh:
        json.dump(tasks, fh, indent=1)
    print("prepared %d task(s)" % len(tasks))


if __name__ == "__main__":
    main()
