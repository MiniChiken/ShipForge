from __future__ import print_function

# What shape are ship traits stored in, and can we write them back?
#
# The info panel's bonus text does NOT come from the cFSD tables. traits.pyj calls
# infobubbles.has_traits(typeID), which is just membership of
#   fsdlite.EveStorage(data='infoBubbleElements', cache='infoBubbles.static')
#     ['infoBubbleTypeBonuses']
# so a typeID absent from that mapping shows no bonuses at all.
#
# fsdlite exposes load/dump/encode/decode, so - as with .black and the FSD tables
# - the client can rewrite its own format for us.
#
#   exefile.exe /py probe_infobubbles.py <result.json> <request.json> /inherit

import json
import os
import sys
import traceback


def safe(v, depth=0):
    if v is None or isinstance(v, (bool, int, long, float, basestring)):
        return v
    if depth > 6:
        return repr(v)[:200]
    if isinstance(v, dict):
        return {str(k): safe(x, depth + 1) for k, x in v.items()}
    try:
        return [safe(x, depth + 1) for x in v]
    except TypeError:
        return repr(v)[:200]


def main():
    result_path = sys.argv[1]
    request_path = sys.argv[2]
    result = {"success": False}
    try:
        import blue
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

        # The fsdlite PACKAGE lives in code.ccp and needs the client's own import
        # hook, which is not active once PYTHONHOME points at the kit runtime.
        # _fsdlite is the native codec, so it imports regardless - and load/dump
        # are all that is needed to read and rewrite the file.
        import _fsdlite
        result["fsdliteApi"] = sorted(n for n in dir(_fsdlite)
                                      if not n.startswith("__"))

        # resolve the logical path to the blob on disk
        path = None
        for attempt in ("GetCachedFileName", "GetCachedFilePath", "FileNameFor"):
            fn = getattr(blue.remoteFileCache, attempt, None)
            if fn is None:
                continue
            try:
                path = fn(req["resource"])
                result["resolvedBy"] = attempt
                break
            except Exception as exc:
                result.setdefault("resolveErrors", {})[attempt] = str(exc)
        if not path:
            path = req.get("fallbackPath")
            result["resolvedBy"] = "fallbackPath"
        result["blobPath"] = safe(path)

        data = _fsdlite.load(path)
        result["loadedType"] = type(data).__name__
        result["topLevelKeys"] = sorted(str(k) for k in data.keys())
        bonuses = data["infoBubbleTypeBonuses"]
        keys = list(bonuses.keys())
        result["bonusCount"] = len(keys)
        result["sampleKeys"] = [str(k) for k in keys[:5]]
        result["keyType"] = type(keys[0]).__name__ if keys else None

        for type_id in req.get("typeIDs", []):
            for candidate in (type_id, str(type_id)):
                if candidate in bonuses:
                    result.setdefault("entries", {})[str(type_id)] = \
                        safe(bonuses[candidate])
                    break
            else:
                result.setdefault("entries", {})[str(type_id)] = None
        result["success"] = True
    except Exception:
        result["error"] = traceback.format_exc()
    open(result_path, "wb").write(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
