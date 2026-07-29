from __future__ import print_function

# Dump turret locators from STOCK hulls so our own follow the real convention
# rather than a guess. Answers two questions the Venator needs:
#   1. how are turret locators NAMED (index/letter scheme, how many)
#   2. do their transforms carry ROTATION, or are they identity translations
#
#   exefile.exe /py probe_template.py <result.json> <request.json> /inherit

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
    result = {"success": False, "hulls": {}}
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
        for res in req["hulls"]:
            try:
                hull = blue.resMan.LoadObject(res)
                blue.resMan.Wait()
                if hull is None:
                    result["hulls"][res] = {"error": "LoadObject returned None"}
                    continue
                result["hulls"][res] = {
                    "name": safe(getattr(hull, "name", None)),
                    "category": safe(getattr(hull, "category", None)),
                    "boundingSphere": safe(getattr(hull, "boundingSphere", None)),
                    "shapeEllipsoidCenter": safe(getattr(hull, "shapeEllipsoidCenter", None)),
                    "shapeEllipsoidRadius": safe(getattr(hull, "shapeEllipsoidRadius", None)),
                    "turrets": [
                        {"name": safe(t.name), "transform": safe(t.transform)}
                        for t in (getattr(hull, "locatorTurrets", []) or [])
                    ],
                    "boosters": [
                        {"transform": safe(i.transform),
                         "lightScale": safe(getattr(i, "lightScale", None)),
                         "hasTrail": safe(getattr(i, "hasTrail", None)),
                         "functionality": safe(getattr(i, "functionality", None))}
                        for i in (getattr(getattr(hull, "booster", None), "items", []) or [])
                    ],
                    "otherLocatorFields": [
                        f for f in dir(hull)
                        if "ocator" in f and not f.startswith("_")
                    ],
                }
            except Exception:
                result["hulls"][res] = {"error": traceback.format_exc()}
        result["success"] = True
    except Exception:
        result["error"] = traceback.format_exc()
    open(result_path, "wb").write(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
