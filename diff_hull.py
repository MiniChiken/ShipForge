"""Structural diff between a built hull and the stock hull it replaces.

Guessing one difference at a time costs a login cycle each. This walks both
files and reports every structural discrepancy at once.
"""
import struct
import sys

import granny
import grobj


def summarize(path_or_bytes, label):
    data = path_or_bytes if isinstance(path_or_bytes, bytes) else open(path_or_bytes, "rb").read()
    g = granny.GrannyFile(data)
    r = grobj.ObjectReader(g)
    root = r.root()
    vt = g.type_tree(6, 0)
    out = {
        "label": label,
        "magic": "CCP" if g.magic == granny.MAGIC_CCP else "RAD",
        "sections_compressed": [s["compression"] for s in g.sections],
        "vertex_format": [(m["name"], m["type"], m["array"]) for m in vt],
        "stride": sum(grobj.member_size(m) for m in vt),
        "counts": {k: root[k]["count"] for k in
                   ("Textures", "Materials", "Skeletons", "VertexDatas",
                    "TriTopologies", "Meshes", "Models", "TrackGroups", "Animations")},
        "art_tool": (root.get("ArtToolInfo") or {}).get("FromArtToolName"),
        "units_per_meter": (root.get("ArtToolInfo") or {}).get("UnitsPerMeter"),
        "mesh_names": [m["Name"] for m in root["Meshes"]["items"]],
        "model_name": root["Models"]["items"][0]["Name"] if root["Models"]["count"] else None,
        "skeleton": None,
        "meshes": [],
    }
    if root["Skeletons"]["count"]:
        sk = root["Skeletons"]["items"][0]
        out["skeleton"] = (sk["Name"], sk["Bones"]["count"],
                           [b["Name"] for b in (sk["Bones"]["items"] or [])])
    for m in root["Meshes"]["items"]:
        tt = m["PrimaryTopology"]
        out["meshes"].append({
            "name": m["Name"],
            "idx16": tt["Indices16"]["count"],
            "idx32": tt["Indices"]["count"],
            "groups": [(x["MaterialIndex"], x["TriFirst"], x["TriCount"])
                       for x in (tt["Groups"]["items"] or [])],
            "bindings": m["MaterialBindings"]["count"],
            "bone_bindings": m["BoneBindings"]["count"],
            "morphs": m["MorphTargets"]["count"],
        })
    return out


def diff(a, b):
    print("=" * 64)
    print("%-28s | %s" % (a["label"], b["label"]))
    print("=" * 64)
    for key in ("magic", "stride", "art_tool", "units_per_meter", "model_name"):
        mark = "  " if a[key] == b[key] else "!!"
        print("%s %-18s %-22s | %s" % (mark, key, a[key], b[key]))
    print()
    for k in a["counts"]:
        mark = "  " if a["counts"][k] == b["counts"][k] else "!!"
        print("%s count.%-16s %-22s | %s" % (mark, k, a["counts"][k], b["counts"][k]))
    print()
    mark = "  " if a["vertex_format"] == b["vertex_format"] else "!!"
    print("%s vertex_format" % mark)
    print("     %s" % (a["vertex_format"],))
    print("     %s" % (b["vertex_format"],))
    print()
    mark = "  " if a["skeleton"] == b["skeleton"] else "!!"
    print("%s skeleton  %s | %s" % (mark, a["skeleton"], b["skeleton"]))
    print()
    print("   mesh names:")
    for i in range(max(len(a["mesh_names"]), len(b["mesh_names"]))):
        x = a["mesh_names"][i] if i < len(a["mesh_names"]) else "-"
        y = b["mesh_names"][i] if i < len(b["mesh_names"]) else "-"
        print("     %-26s | %s" % (x, y))
    print()
    print("   first mesh detail:")
    ma, mb = a["meshes"][0], b["meshes"][0]
    for k in ("idx16", "idx32", "groups", "bindings", "bone_bindings", "morphs"):
        mark = "  " if ma[k] == mb[k] else "!!"
        print("   %s %-14s %-24s | %s" % (mark, k, ma[k], mb[k]))
