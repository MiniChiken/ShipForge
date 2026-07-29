from __future__ import print_function

# Dump the lighting sets from a stock hull AND from our live one.
#
# A hull's lighting lives in spotlightSets / planeSets / spriteSets (lightSets and
# hazeSets are empty on the hulls checked). Cloning a donor inherits ITS sets,
# positioned for ITS geometry - so this also answers whether our hull is carrying
# Maelstrom lights in places our model has no hull.
#
#   exefile.exe /py probe_lights.py <result.json> <request.json> /inherit

import json
import os
import sys
import traceback

LIGHT_FIELDS = ("spotlightSets", "planeSets", "spriteSets", "lightSets",
                "hazeSets", "decalSets", "bannerSets")


def safe(v):
    if v is None or isinstance(v, (bool, int, long, float, basestring)):
        return v
    if isinstance(v, (tuple, list)):
        return [safe(x) for x in v]
    return repr(v)


def numeric_seq(value):
    """True for a sequence of numbers, or of sequences of numbers."""
    for element in value:
        if isinstance(element, (int, long, float)):
            continue
        try:
            inner = list(element)
        except TypeError:
            return False
        if not all(isinstance(x, (int, long, float)) for x in inner):
            return False
    return True


def dump(obj, depth=0, max_depth=3):
    """Recursive field dump, shallow enough to stay readable."""
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
            out[name] = dump(value, depth + 1, max_depth)
            continue
        if not n:
            out[name] = []
        elif numeric_seq(value):
            # plain numbers, or nested numeric rows like a 4x4 transform. These
            # have no attributes to walk, so recursing would erase them.
            out[name] = safe(list(value))
        else:
            out[name] = [dump(v, depth + 1, max_depth) for v in list(value)[:8]]
            if n > 8:
                out[name].append("... %d total" % n)
    return out


def lights_of(hull):
    out = {}
    for field in LIGHT_FIELDS:
        sets = getattr(hull, field, None)
        if sets is None:
            continue
        out[field] = {"count": len(sets),
                      "items": [dump(s, 0, 5) for s in list(sets)[:4]]}
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

        donor = blue.resMan.LoadObject(req["donorHull"])
        blue.resMan.Wait()
        result["donor"] = {"name": safe(donor.name), "lights": lights_of(donor)}

        agg = blue.resMan.LoadObject(req["aggregateResource"])
        blue.resMan.Wait()
        for h in agg.hull:
            if h.name == req["hullName"]:
                result["ours"] = {"name": safe(h.name), "lights": lights_of(h)}
                break
        result["success"] = True
    except Exception:
        result["error"] = traceback.format_exc()
    open(result_path, "wb").write(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
