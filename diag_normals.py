"""Check whether source materials actually feed the Principled Normal input.

The baked normal map came out flat (std ~2 vs stock ~20-30), meaning the bake
captured only the mesh's own geometric normals and none of the model's normal
map detail. Either the Normal inputs are unlinked, or the bake is not seeing
them.

Run: blender --background venator_atlas.blend --python diag_normals.py
"""
import bpy

obj = next(o for o in bpy.data.objects if o.type == "MESH")
me = obj.data
print("%-32s %-8s %-10s %s" % ("material", "normal?", "via", "image"))
linked = 0
for mat in me.materials:
    if mat is None or not mat.use_nodes:
        print("%-32s %-8s" % (getattr(mat, "name", "<none>"), "no-nodes"))
        continue
    bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        print("%-32s %-8s" % (mat.name[:32], "no-bsdf"))
        continue
    inp = bsdf.inputs.get("Normal")
    if inp is None or not inp.is_linked:
        print("%-32s %-8s" % (mat.name[:32], "NO"))
        continue
    src = inp.links[0].from_node
    img = "-"
    if src.type == "NORMAL_MAP":
        cin = src.inputs.get("Color")
        if cin and cin.is_linked:
            n2 = cin.links[0].from_node
            img = getattr(getattr(n2, "image", None), "name", n2.type)
    else:
        img = getattr(getattr(src, "image", None), "name", src.type)
    linked += 1
    print("%-32s %-8s %-10s %s" % (mat.name[:32], "yes", src.type, img[:40]))
print()
print("materials with a linked Normal input: %d / %d" % (linked, len(me.materials)))
