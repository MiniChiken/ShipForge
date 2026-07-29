from __future__ import print_function

# Python 2.7 worker, run inside the EVE client:
#     exefile.exe /py author_venator.py <result.json> <request.json> /inherit
#
# Purpose-built variant of the Elysian kit's native_author_hull.py. The kit's
# generic patcher replaces native lists wholesale, which would mean reproducing
# every EveSOFDataHullArea shader parameter byte-perfectly just to repoint a
# texture. This edits textures IN PLACE by slot name instead, and builds booster
# and turret locators from positions measured off the actual Venator geometry.

import json
import math
import os
import sys
import traceback


def safe(value):
    if value is None or isinstance(value, (bool, int, long, float, basestring)):
        return value
    if isinstance(value, (tuple, list)):
        return [safe(v) for v in value]
    return repr(value)


def initialize_resource_cache(blue):
    if not blue.paths.IsFileSystemRegistered("Remote"):
        blue.paths.RegisterFileSystemBeforeLocal("Remote")
    blue.remoteFileCache.cacheFolder = os.environ["ELYSIAN_SHIPKIT_RESFILES"]
    blue.remoteFileCache.server = "https://clientresources.eveonline.com/"
    blue.remoteFileCache.backupServer = blue.remoteFileCache.server
    for filename in ("resfileindex.txt", "resfileindex_Windows.txt"):
        path = os.path.join(os.getcwd(), filename)
        if os.path.isfile(path):
            handle = open(path, "rb")
            try:
                blue.remoteFileCache.AddFileIndex(handle.read())
            finally:
                handle.close()


def read_json(path):
    h = open(path, "rb")
    try:
        return json.loads(h.read())
    finally:
        h.close()


def write_json(path, value):
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    h = open(path, "wb")
    try:
        h.write(json.dumps(value, indent=2, sort_keys=True))
    finally:
        h.close()


def load_object(blue, resource_path):
    value = blue.resMan.LoadObject(resource_path)
    blue.resMan.Wait()
    if value is None:
        raise RuntimeError("LoadObject returned None for %s" % resource_path)
    return value


def save_object(blue, value, output_path):
    parent = os.path.dirname(output_path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    if os.path.isfile(output_path):
        os.unlink(output_path)
    if not blue.resMan.SaveObject(value, output_path):
        raise RuntimeError("SaveObject failed for %s" % output_path)
    blue.resMan.Wait()
    return load_object(blue, output_path)


def retarget_textures(hull, mapping, report):
    """Rewrite EveSOFDataTexture.resFilePath in place, matched by slot name.

    Editing in place preserves each area's shader and parameter objects exactly
    as the template had them - only the resource path changes.
    """
    for area_field in ("opaqueAreas", "decalAreas", "transparentAreas",
                       "additiveAreas", "distortionAreas"):
        areas = getattr(hull, area_field, None)
        if areas is None:
            continue
        for area in areas:
            for tex in getattr(area, "textures", []) or []:
                name = getattr(tex, "name", None)
                if name in mapping:
                    old = getattr(tex, "resFilePath", None)
                    tex.resFilePath = mapping[name]
                    report.append({"area": area_field,
                                   "areaName": safe(getattr(area, "name", None)),
                                   "slot": name, "from": safe(old),
                                   "to": mapping[name]})


def identity_transform(pos, scale=(1.0, 1.0, 1.0)):
    """Row-major 4x4; row 3 is translation, matching the kit's examples."""
    return ((scale[0], 0.0, 0.0, 0.0),
            (0.0, scale[1], 0.0, 0.0),
            (0.0, 0.0, scale[2], 0.0),
            (pos[0], pos[1], pos[2], 1.0))


def rebuild_boosters(blue, hull, specs, report):
    booster = hull.booster
    items = booster.items
    while len(items):
        items.pop()
    for spec in specs:
        item = blue.classes.CreateInstance("trinity.EveSOFDataHullBoosterItem")
        item.transform = identity_transform(spec["pos"], spec.get("scale", (1.0, 1.0, 1.0)))
        item.hasTrail = bool(spec.get("hasTrail", True))
        item.lightScale = float(spec.get("lightScale", 1.0))
        item.atlasIndex0 = int(spec.get("atlasIndex0", 0))
        item.atlasIndex1 = int(spec.get("atlasIndex1", 0))
        item.functionality = (0.0, 1.0, 1.0, 1.0)
        items.append(item)
        report.append({"pos": spec["pos"], "scale": spec.get("scale")})
    return len(items)


def mount_transform(pos, normal):
    """Locator basis for a turret mounted on a surface facing `normal`.

    Read off the stock hulls: the rows are the local X/Y/Z axes, local Y is the
    mount normal and local Z points along the hull's forward axis, with
    local X = Y x Z. Verified against ab2_t1's locator_turret_1a (Y = -X,
    outboard to port) and 1b (Y = +X, outboard to starboard), and against the
    identity case used for centreline dorsal mounts.
    """
    n = list(normal)
    length = math.sqrt(sum(v * v for v in n)) or 1.0
    ny = [v / length for v in n]

    fwd = (0.0, 0.0, 1.0)
    # re-orthogonalise forward against the normal so the basis stays orthonormal
    dot = sum(a * b for a, b in zip(ny, fwd))
    nz = [f - dot * y for f, y in zip(fwd, ny)]
    length = math.sqrt(sum(v * v for v in nz))
    if length < 1e-6:                      # normal parallel to forward
        nz, length = [0.0, 1.0, 0.0], 1.0
    nz = [v / length for v in nz]

    nx = [ny[1] * nz[2] - ny[2] * nz[1],
          ny[2] * nz[0] - ny[0] * nz[2],
          ny[0] * nz[1] - ny[1] * nz[0]]

    return ((nx[0], nx[1], nx[2], 0.0),
            (ny[0], ny[1], ny[2], 0.0),
            (nz[0], nz[1], nz[2], 0.0),
            (pos[0], pos[1], pos[2], 1.0))


def rebuild_turrets(blue, hull, specs, report):
    locs = hull.locatorTurrets
    while len(locs):
        locs.pop()
    for spec in specs:
        loc = blue.classes.CreateInstance("trinity.EveSOFDataHullLocator")
        loc.name = str(spec["name"])
        normal = spec.get("normal")
        loc.transform = (mount_transform(spec["pos"], normal) if normal
                         else identity_transform(spec["pos"]))
        locs.append(loc)
        report.append({"name": spec["name"], "pos": spec["pos"],
                       "normal": normal, "transform": safe(loc.transform)})
    return len(locs)


def hull_summary(hull):
    return {
        "name": safe(getattr(hull, "name", None)),
        "description": safe(getattr(hull, "description", None)),
        "category": safe(getattr(hull, "category", None)),
        "geometryResFilePath": safe(getattr(hull, "geometryResFilePath", None)),
        "isSkinned": safe(getattr(hull, "isSkinned", None)),
        "boundingSphere": safe(getattr(hull, "boundingSphere", None)),
        "shapeEllipsoidCenter": safe(getattr(hull, "shapeEllipsoidCenter", None)),
        "shapeEllipsoidRadius": safe(getattr(hull, "shapeEllipsoidRadius", None)),
        "opaqueAreaCount": len(getattr(hull, "opaqueAreas", []) or []),
        "boosterItemCount": len(getattr(getattr(hull, "booster", None), "items", []) or []),
        "turretLocatorCount": len(getattr(hull, "locatorTurrets", []) or []),
        "textures": [
            {"area": safe(getattr(a, "name", None)), "slot": safe(getattr(t, "name", None)),
             "path": safe(getattr(t, "resFilePath", None))}
            for a in (getattr(hull, "opaqueAreas", []) or [])
            for t in (getattr(a, "textures", []) or [])
        ],
    }


def main():
    result_path = sys.argv[1]
    request_path = sys.argv[2]
    result = {"success": False}
    try:
        import blue
        # Required: importing the Trinity extension registers the trinity.*
        # classes. Without it LoadObject cannot deserialize a
        # trinity.EveSOFDataHull and silently returns None.
        import _trinity_dx11
        initialize_resource_cache(blue)
        req = read_json(request_path)

        hull = load_object(blue, req["templateHullResource"])
        result["template"] = hull_summary(hull)

        for field, value in sorted(req.get("scalars", {}).items()):
            setattr(hull, field, tuple(value) if isinstance(value, list) else value)

        texture_report = []
        retarget_textures(hull, req.get("textures", {}), texture_report)
        result["textureChanges"] = texture_report

        booster_report = []
        result["boosterItems"] = rebuild_boosters(
            blue, hull, req.get("boosters", []), booster_report)
        result["boosterDetail"] = booster_report

        turret_report = []
        result["turretLocators"] = rebuild_turrets(
            blue, hull, req.get("turrets", []), turret_report)
        result["turretDetail"] = turret_report

        if hasattr(hull, "Validate"):
            result["validation"] = safe(hull.Validate())

        authored = save_object(blue, hull, req["outputHullBlack"])
        result["authored"] = hull_summary(authored)
        if result["authored"]["name"] != req["scalars"].get("name"):
            raise RuntimeError("hull name did not survive native reload")

        agg_out = req.get("outputAggregateBlack")
        if agg_out:
            aggregate = load_object(blue, req["aggregateResource"])
            hulls = aggregate.hull
            before = len(hulls)
            # Idempotent: re-authoring should update the hull in place, not fail
            # because a previous run already merged it.
            existing = None
            for index, h in enumerate(hulls):
                if h.name == authored.name:
                    existing = index
                    break
            if existing is None:
                hulls.append(authored)
                result["mergeMode"] = "append"
            else:
                try:
                    hulls[existing] = authored
                    result["mergeMode"] = "replace-in-place"
                except Exception:
                    kept = [h for h in hulls if h.name != authored.name]
                    while len(hulls):
                        hulls.pop()
                    for h in kept:
                        hulls.append(h)
                    hulls.append(authored)
                    result["mergeMode"] = "rebuild"
            reloaded = save_object(blue, aggregate, agg_out)
            after = list(reloaded.hull)
            result["aggregate"] = {
                "beforeHullCount": before,
                "afterHullCount": len(after),
                "newHullPresent": authored.name in set(h.name for h in after),
            }
            if not result["aggregate"]["newHullPresent"]:
                raise RuntimeError("new hull missing after aggregate reload")
        result["success"] = True
    except Exception:
        result["error"] = traceback.format_exc()
    write_json(result_path, result)
    return 0 if result["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
