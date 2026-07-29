"""Build a Venator gr2 structured exactly like a stock EVE hull.

Differences from the first attempt, all taken from the original abc1_t1:
  * ONE shape with a 7-mesh LOD chain, not 3 arbitrarily-named chunks
  * Materials array is EMPTY - EVE drives materials from the SOF .black, and the
    stock hull has Materials=0 while still carrying MaterialBindings per mesh
  * Model is named for the hull
  * triangle-group count per mesh == the SOF hull's opaque-area count
"""
import json
import os
import struct
import sys

import gr2write as W
from build_venator import (ROOT, VERTEX, IDENTITY, IDENTITY4X4)

# Skinned hulls use rigid binding: BoneIndices UInt8[4] and NO BoneWeights.
# Measured from readable skinned hulls (ade2_t1, ade2_t2) - stride 24.
VERTEX_SKINNED = [W.Member("Position", W.REAL32, array=3),
                  W.Member("BoneIndices", W.UINT8, array=4),
                  W.Member("Tangent", W.NORMAL_UINT8, array=4),
                  W.Member("TextureCoordinates0", W.REAL16, array=2)]

HERE = os.path.dirname(os.path.abspath(__file__))


def double_wind(ibytes, ntris, width=2):
    """Emit each triangle twice, both windings, so backface culling can never
    hide geometry.

    Reversing the winding wholesale made the hull FULLY invisible, while the
    original made only some faces vanish - i.e. the source mesh has mixed
    winding and no single global choice is right. Doubling costs triangles but
    removes the failure mode entirely; vertex count is unchanged so the 16-bit
    index limit still holds.
    """
    f3 = "<3H" if width == 2 else "<3I"
    f6 = "<6H" if width == 2 else "<6I"
    out = bytearray()
    for t in range(ntris):
        a, b, c = struct.unpack_from(f3, ibytes, t * 3 * width)
        out.extend(struct.pack(f6, a, b, c, a, c, b))
    return bytes(out)


def build(outpath, hull_name, area_count, shape_name=None, lod_suffixes=None,
          double_sided=True):
    """shape_name/lod_suffixes let the meshes be named exactly like the hull
    being substituted - ab1_t1 uses "ab1_TShape1" with a 320..10 ladder, while
    abc1_t1 uses a 640..20 one, so the ladder is per-hull and worth matching."""
    man = json.load(open(os.path.join(HERE, "venator_lod.json")))
    blob = open(os.path.join(HERE, "venator_lod.bin"), "rb").read()
    stride = man["stride"]
    vfmt = VERTEX_SKINNED if man.get("skinned") else VERTEX
    ibase = man["index_base"]

    if shape_name or lod_suffixes:
        shape = shape_name or man["shape"]
        sufs = lod_suffixes or [lv["name"][len(man["shape"]):] for lv in man["levels"]]
        for lv, suf in zip(man["levels"], sufs):
            lv["name"] = shape + suf

    meshes = []
    for lv in man["levels"]:
        vs = lv["vertex_offset"]
        vbytes = blob[vs:vs + lv["vertex_count"] * stride]
        ist = ibase + lv["index_offset"]
        nidx = lv["triangle_count"] * 3
        # oriented bounding box over this level's positions (stride 20, pos at 0)
        lo = [1e30] * 3
        hi = [-1e30] * 3
        for i in range(lv["vertex_count"]):
            px, py, pz = struct.unpack_from("<3f", vbytes, i * stride)
            for k, val in enumerate((px, py, pz)):
                lo[k] = min(lo[k], val)
                hi[k] = max(hi[k], val)
        obb = (lo, hi)

        width = 4 if lv.get("bits32") else 2
        ibytes = blob[ist:ist + nidx * width]
        total = lv["triangle_count"]
        if double_sided:
            ibytes = double_wind(ibytes, total, width)
            total *= 2
            nidx = total * 3
        groups = [{"MaterialIndex": 0, "TriFirst": 0, "TriCount": total}]
        for i in range(1, area_count):
            groups.append({"MaterialIndex": i, "TriFirst": total, "TriCount": 0})
        meshes.append({
            "Name": lv["name"],
            "PrimaryVertexData": {
                "Vertices": (vfmt, vbytes, lv["vertex_count"]),
                "VertexComponentNames": [], "VertexAnnotationSets": [],
            },
            "MorphTargets": [],
            "PrimaryTopology": {
                "Groups": groups,
                "Indices": ("raw", nidx, ibytes) if lv.get("bits32") else ("raw", 0, b""),
                "Indices16": ("raw", 0, b"") if lv.get("bits32") else ("raw", nidx, ibytes),
                "VertexToVertexMap": ("raw", 0, b""),
                "VertexToTriangleMap": ("raw", 0, b""),
                "SideToNeighborMap": ("raw", 0, b""),
                "PolygonIndexStarts": ("raw", 0, b""),
                "PolygonIndices": ("raw", 0, b""),
                "BonesForTriangle": ("raw", 0, b""),
                "TriangleToBoneIndices": ("raw", 0, b""),
                "TriAnnotationSets": [],
            },
            # bindings exist per area but carry no gr2-side material, matching
            # the stock hull where Materials is empty
            "MaterialBindings": [{"Material": None} for _ in range(area_count)],
            # Stock hulls bind every mesh to the single root bone with an OBB.
            # Without this the mesh is not attached to the skeleton and trinity
            # has nothing to transform it by - a strong candidate for the hull
            # rendering as completely invisible.
            "BoneBindings": [{
                "BoneName": hull_name,
                "OBBMin": list(obb[0]), "OBBMax": list(obb[1]),
                "TriangleIndices": ("raw", 0, b""),
            }],
        })

    # single root bone named for the hull, exactly as stock hulls do
    skeleton = {
        "Name": hull_name, "LODType": 0,
        "Bones": [{"Name": hull_name, "ParentIndex": -1,
                   "Transform": IDENTITY,
                   "InverseWorldTransform": IDENTITY4X4, "LODError": 0.0}],
    }

    root = {
        "ArtToolInfo": {
            "FromArtToolName": "Blender", "ArtToolMajorRevision": 5,
            "ArtToolMinorRevision": 2, "ArtToolPointerSize": 64,
            "UnitsPerMeter": 100.0,
            "Origin": [0.0, 0.0, 0.0], "RightVector": [1.0, 0.0, 0.0],
            "UpVector": [0.0, 1.0, 0.0], "BackVector": [0.0, 0.0, -1.0],
        },
        "ExporterInfo": {
            "ExporterName": "evejs venator pipeline",
            "ExporterMajorRevision": 1, "ExporterMinorRevision": 0,
            "ExporterCustomization": 0, "ExporterBuildNumber": 1,
        },
        "FromFileName": "%s.blend" % hull_name,
        "Textures": [], "Materials": [], "Skeletons": [skeleton],
        # Stock registers only ONE entry in each root array even though it has
        # 7 meshes - the rest are reached solely through the meshes. Match that.
        "VertexDatas": [meshes[0]["PrimaryVertexData"]],
        "TriTopologies": [meshes[0]["PrimaryTopology"]],
        "Meshes": meshes,
        "Models": [{"Name": hull_name, "Skeleton": skeleton,
                    "InitialPlacement": IDENTITY,
                    "MeshBindings": [{"Mesh": m} for m in meshes]}],
        "TrackGroups": [], "Animations": [],
    }
    w = W.GrannyWriter()
    data = w.build(ROOT, root)
    open(outpath, "wb").write(data)
    return data, man


if __name__ == "__main__":
    out = sys.argv[1]
    hull = sys.argv[2]
    areas = int(sys.argv[3])
    shape = sys.argv[4] if len(sys.argv) > 4 else None
    sufs = sys.argv[5].split(",") if len(sys.argv) > 5 else None
    data, man = build(out, hull, areas, shape, sufs)
    print("wrote %s: %d bytes, %d LOD meshes, %d areas"
          % (out, len(data), len(man["levels"]), areas))
