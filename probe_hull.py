from __future__ import print_function

# Read the LIVE venator_t1 hull out of the published data.black and dump the
# values that actually reach the renderer. Confirms whether an authoring change
# landed, rather than inferring it from the file we wrote.
#
#   exefile.exe /py probe_hull.py <result.json> <request.json> /inherit

import json
import os
import sys
import traceback


def safe(v):
    if v is None or isinstance(v, (bool, int, long, float, basestring)):
        return v
    if isinstance(v, (tuple, list)):
        return [safe(x) for x in v]
    return repr(v)


def main():
    result_path = sys.argv[1]
    request_path = sys.argv[2]
    result = {"success": False}
    try:
        import blue
        import _trinity_dx11
        if not blue.paths.IsFileSystemRegistered("Remote"):
            blue.paths.RegisterFileSystemBeforeLocal("Remote")
        blue.remoteFileCache.cacheFolder = os.environ["ELYSIAN_SHIPKIT_RESFILES"]
        blue.remoteFileCache.server = "https://clientresources.eveonline.com/"
        blue.remoteFileCache.backupServer = blue.remoteFileCache.server
        for name in ("resfileindex.txt", "resfileindex_Windows.txt"):
            p = os.path.join(os.getcwd(), name)
            if os.path.isfile(p):
                h = open(p, "rb")
                try:
                    blue.remoteFileCache.AddFileIndex(h.read())
                finally:
                    h.close()

        req = json.loads(open(request_path, "rb").read())
        agg = blue.resMan.LoadObject(req["aggregateResource"])
        blue.resMan.Wait()
        hull = None
        for h in agg.hull:
            if h.name == req["hullName"]:
                hull = h
                break
        if hull is None:
            raise RuntimeError("hull %s not in aggregate" % req["hullName"])

        result["hull"] = {
            "name": safe(hull.name),
            "geometryResFilePath": safe(hull.geometryResFilePath),
            "boundingSphere": safe(hull.boundingSphere),
            "shapeEllipsoidCenter": safe(hull.shapeEllipsoidCenter),
            "shapeEllipsoidRadius": safe(hull.shapeEllipsoidRadius),
        }
        result["boosters"] = [
            {"transform": safe(i.transform), "lightScale": safe(i.lightScale)}
            for i in hull.booster.items
        ]
        result["turrets"] = [
            {"name": safe(t.name), "transform": safe(t.transform)}
            for t in hull.locatorTurrets
        ]
        result["success"] = True
    except Exception:
        result["error"] = traceback.format_exc()
    open(result_path, "wb").write(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
