from __future__ import print_function

# What material slots does a faction supply?
#
# An area's albedo is TINTED by the faction's material slots, selected per-pixel
# by the _m map. So the same _m map means different brightness on different
# factions - a map tuned for amarrbase's white_ivory_matt will render dark if the
# hull is flagged minmatarbase and slot 1 there is a rust material.
#
#   exefile.exe /py probe_faction.py <result.json> <request.json> /inherit

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


def fields(obj, depth=0, max_depth=2):
    if depth > max_depth:
        return "..."
    out = {"__class__": type(obj).__name__}
    for name in dir(obj):
        if name.startswith("_"):
            continue
        try:
            value = getattr(obj, name)
        except Exception:
            continue
        if callable(value):
            continue
        if value is None or isinstance(value, (bool, int, long, float, basestring)):
            out[name] = value
            continue
        try:
            n = len(value)
        except (TypeError, AttributeError):
            out[name] = fields(value, depth + 1, max_depth)
            continue
        if not n:
            out[name] = []
        elif all(isinstance(x, (int, long, float)) for x in value):
            out[name] = safe(list(value))
        else:
            out[name] = [fields(v, depth + 1, max_depth) for v in list(value)[:8]]
    return out


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

        result["aggregateFields"] = sorted(
            f for f in dir(agg) if not f.startswith("_")
            and not callable(getattr(agg, f, None)))

        wanted = set(req["factions"])
        result["factions"] = {}
        for f in getattr(agg, "faction", []) or []:
            if f.name in wanted:
                result["factions"][f.name] = fields(f)

        # material library, so slot names can be resolved to actual colours
        result["materials"] = {}
        for m in getattr(agg, "material", []) or []:
            result["materials"][m.name] = fields(m, 1, 2)
        result["success"] = True
    except Exception:
        result["error"] = traceback.format_exc()
    open(result_path, "wb").write(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
