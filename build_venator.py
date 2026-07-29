"""Build venator_t1.gr2 from the Blender intermediate.

Schema mirrors a real EVE hull (ab1_t1) member-for-member so trinity sees a
structure it already knows how to consume.
"""
import json
import os
import struct
import sys

import gr2write as W

HERE = os.path.dirname(os.path.abspath(__file__))

# -- schema, mirroring ab1_t1's type tree ---------------------------------
MAP = [W.Member("Usage", W.STRING), W.Member("Map", W.REFERENCE)]
MATERIAL = [W.Member("Name", W.STRING), W.Member("Maps", W.REF_TO_ARRAY, MAP),
            W.Member("Texture", W.REFERENCE), W.Member("ExtendedData", W.VARIANT_REF)]

VERTEX = [W.Member("Position", W.REAL32, array=3),
          W.Member("Tangent", W.NORMAL_UINT8, array=4),
          W.Member("TextureCoordinates0", W.REAL16, array=2)]

STRING_ITEM = [W.Member("String", W.STRING)]
VERTEX_DATA = [W.Member("Vertices", W.REF_TO_VARIANT_ARRAY),
               W.Member("VertexComponentNames", W.REF_TO_ARRAY, STRING_ITEM),
               W.Member("VertexAnnotationSets", W.REF_TO_ARRAY, STRING_ITEM)]

GROUP = [W.Member("MaterialIndex", W.INT32), W.Member("TriFirst", W.INT32),
         W.Member("TriCount", W.INT32)]
I32 = [W.Member("Int32", W.INT32)]
I16 = [W.Member("Int16", W.INT16)]
TRI_TOPOLOGY = [
    W.Member("Groups", W.REF_TO_ARRAY, GROUP),
    W.Member("Indices", W.REF_TO_ARRAY, I32),
    W.Member("Indices16", W.REF_TO_ARRAY, I16),
    W.Member("VertexToVertexMap", W.REF_TO_ARRAY, I32),
    W.Member("VertexToTriangleMap", W.REF_TO_ARRAY, I32),
    W.Member("SideToNeighborMap", W.REF_TO_ARRAY, I32),
    W.Member("PolygonIndexStarts", W.REF_TO_ARRAY, I32),
    W.Member("PolygonIndices", W.REF_TO_ARRAY, I32),
    W.Member("BonesForTriangle", W.REF_TO_ARRAY, I32),
    W.Member("TriangleToBoneIndices", W.REF_TO_ARRAY, I32),
    W.Member("TriAnnotationSets", W.REF_TO_ARRAY, STRING_ITEM),
]

MORPH = [W.Member("ScalarName", W.STRING), W.Member("VertexData", W.REFERENCE),
         W.Member("DataIsDeltas", W.INT32)]
MAT_BINDING = [W.Member("Material", W.REFERENCE, MATERIAL)]
BONE_BINDING = [W.Member("BoneName", W.STRING), W.Member("OBBMin", W.REAL32, array=3),
                W.Member("OBBMax", W.REAL32, array=3),
                W.Member("TriangleIndices", W.REF_TO_ARRAY, I32)]
MESH = [W.Member("Name", W.STRING),
        W.Member("PrimaryVertexData", W.REFERENCE, VERTEX_DATA),
        W.Member("MorphTargets", W.REF_TO_ARRAY, MORPH),
        W.Member("PrimaryTopology", W.REFERENCE, TRI_TOPOLOGY),
        W.Member("MaterialBindings", W.REF_TO_ARRAY, MAT_BINDING),
        W.Member("BoneBindings", W.REF_TO_ARRAY, BONE_BINDING),
        W.Member("ExtendedData", W.VARIANT_REF)]

# Stock hulls carry a single root bone named after the hull; the Model points at
# it. Without a skeleton trinity has nothing to place the meshes against.
BONE = [W.Member("Name", W.STRING), W.Member("ParentIndex", W.INT32),
        W.Member("Transform", W.TRANSFORM),
        W.Member("InverseWorldTransform", W.REAL32, array=16),
        W.Member("LODError", W.REAL32), W.Member("ExtendedData", W.VARIANT_REF)]
SKELETON = [W.Member("Name", W.STRING), W.Member("Bones", W.REF_TO_ARRAY, BONE),
            W.Member("LODType", W.INT32), W.Member("ExtendedData", W.VARIANT_REF)]

MESH_BINDING = [W.Member("Mesh", W.REFERENCE, MESH)]
MODEL = [W.Member("Name", W.STRING), W.Member("Skeleton", W.REFERENCE, SKELETON),
         W.Member("InitialPlacement", W.TRANSFORM),
         W.Member("MeshBindings", W.REF_TO_ARRAY, MESH_BINDING),
         W.Member("ExtendedData", W.VARIANT_REF)]

IDENTITY4X4 = [1.0, 0.0, 0.0, 0.0,
               0.0, 1.0, 0.0, 0.0,
               0.0, 0.0, 1.0, 0.0,
               0.0, 0.0, 0.0, 1.0]

ART = [W.Member("FromArtToolName", W.STRING),
       W.Member("ArtToolMajorRevision", W.INT32),
       W.Member("ArtToolMinorRevision", W.INT32),
       W.Member("ArtToolPointerSize", W.INT32),
       W.Member("UnitsPerMeter", W.REAL32),
       W.Member("Origin", W.REAL32, array=3), W.Member("RightVector", W.REAL32, array=3),
       W.Member("UpVector", W.REAL32, array=3), W.Member("BackVector", W.REAL32, array=3),
       W.Member("ExtendedData", W.VARIANT_REF)]
EXPORTER = [W.Member("ExporterName", W.STRING),
            W.Member("ExporterMajorRevision", W.INT32),
            W.Member("ExporterMinorRevision", W.INT32),
            W.Member("ExporterCustomization", W.INT32),
            W.Member("ExporterBuildNumber", W.INT32),
            W.Member("ExtendedData", W.VARIANT_REF)]

ROOT = [
    W.Member("ArtToolInfo", W.REFERENCE, ART),
    W.Member("ExporterInfo", W.REFERENCE, EXPORTER),
    W.Member("FromFileName", W.STRING),
    W.Member("Textures", W.ARRAY_OF_REFS, STRING_ITEM),
    W.Member("Materials", W.ARRAY_OF_REFS, MATERIAL),
    W.Member("Skeletons", W.ARRAY_OF_REFS, SKELETON),
    W.Member("VertexDatas", W.ARRAY_OF_REFS, VERTEX_DATA),
    W.Member("TriTopologies", W.ARRAY_OF_REFS, TRI_TOPOLOGY),
    W.Member("Meshes", W.ARRAY_OF_REFS, MESH),
    W.Member("Models", W.ARRAY_OF_REFS, MODEL),
    W.Member("TrackGroups", W.ARRAY_OF_REFS, STRING_ITEM),
    W.Member("Animations", W.ARRAY_OF_REFS, STRING_ITEM),
    W.Member("ExtendedData", W.VARIANT_REF),
]

IDENTITY = (0,
            0.0, 0.0, 0.0,
            0.0, 0.0, 0.0, 1.0,
            1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)


def area_groups(chunk, area_count):
    """Collapse per-material groups into exactly `area_count` triangle groups.

    A SOF hull binds triangle groups to its opaque-area records BY INDEX, so the
    group count must equal the hull's area count. ab1_t1 has two areas
    (area_hull, area_booster) and its stock gr2 has exactly two groups.
    All geometry goes to area 0; trailing areas get empty groups.
    """
    total = chunk["triangle_count"]
    groups = [{"MaterialIndex": 0, "TriFirst": 0, "TriCount": total}]
    for i in range(1, area_count):
        groups.append({"MaterialIndex": i, "TriFirst": total, "TriCount": 0})
    return groups


def build(outpath, area_count=2, area_names=("area_hull", "area_booster")):
    man = json.load(open(os.path.join(HERE, "venator_mesh.json")))
    blob = open(os.path.join(HERE, "venator_mesh.bin"), "rb").read()
    stride = man["stride"]
    ibase = man["index_base"]

    materials = [{"Name": n, "Maps": [], "Texture": None}
                 for n in area_names[:area_count]]

    meshes = []
    for c in man["chunks"]:
        vstart = c["vertex_offset"]
        vbytes = blob[vstart:vstart + c["vertex_count"] * stride]
        istart = ibase + c["index_offset"]
        ibytes = blob[istart:istart + c["triangle_count"] * 3 * 2]
        meshes.append({
            "Name": c["name"],
            "PrimaryVertexData": {
                "Vertices": (VERTEX, vbytes, c["vertex_count"]),
                "VertexComponentNames": [{"String": m.name} for m in VERTEX],
                "VertexAnnotationSets": [],
            },
            "MorphTargets": [],
            "PrimaryTopology": {
                "Groups": area_groups(c, area_count),
                "Indices": ("raw", 0, b""),
                "Indices16": ("raw", c["triangle_count"] * 3, ibytes),
                "VertexToVertexMap": ("raw", 0, b""),
                "VertexToTriangleMap": ("raw", 0, b""),
                "SideToNeighborMap": ("raw", 0, b""),
                "PolygonIndexStarts": ("raw", 0, b""),
                "PolygonIndices": ("raw", 0, b""),
                "BonesForTriangle": ("raw", 0, b""),
                "TriangleToBoneIndices": ("raw", 0, b""),
                "TriAnnotationSets": [],
            },
            "MaterialBindings": [{"Material": m} for m in materials],
            "BoneBindings": [],
        })

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
        "FromFileName": "venator_t1.blend",
        "Textures": [], "Materials": materials, "Skeletons": [],
        "VertexDatas": [m["PrimaryVertexData"] for m in meshes],
        "TriTopologies": [m["PrimaryTopology"] for m in meshes],
        "Meshes": meshes,
        "Models": [{"Name": "venator_t1", "Skeleton": None,
                    "InitialPlacement": IDENTITY,
                    "MeshBindings": [{"Mesh": m} for m in meshes]}],
        "TrackGroups": [], "Animations": [],
    }

    w = W.GrannyWriter()
    data = w.build(ROOT, root)
    with open(outpath, "wb") as fh:
        fh.write(data)
    return data, man


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "venator_t1.gr2")
    data, man = build(out)
    print("wrote %s: %d bytes" % (out, len(data)))
    print("chunks=%d materials=%d" % (len(man["chunks"]), len(man["materials"])))
