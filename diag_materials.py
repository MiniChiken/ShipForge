"""Report why some material cells bake empty.

Run: blender --background venator_atlas.blend --python diag_materials.py
"""
import bpy

obj = next(o for o in bpy.data.objects if o.type == "MESH")
me = obj.data
counts = {}
for poly in me.polygons:
    counts[poly.material_index] = counts.get(poly.material_index, 0) + 1

# UV span per material in the atlas layer
uvl = me.uv_layers.get("atlas") or me.uv_layers.active
spans = {}
for poly in me.polygons:
    mi = poly.material_index
    for li in poly.loop_indices:
        u, v = uvl.data[li].uv
        lo, hi = spans.get(mi, ((9, 9), (-9, -9)))
        spans[mi] = ((min(lo[0], u), min(lo[1], v)), (max(hi[0], u), max(hi[1], v)))

print("idx  polys   material                       nodes bsdf basecolor  atlas-uv span")
for i, mat in enumerate(me.materials):
    n = counts.get(i, 0)
    name = mat.name if mat else "<none>"
    has_nodes = bool(mat and mat.use_nodes)
    bsdf = None
    linked = "-"
    if has_nodes:
        bsdf = next((x for x in mat.node_tree.nodes if x.type == "BSDF_PRINCIPLED"), None)
        if bsdf:
            bc = bsdf.inputs["Base Color"]
            linked = "linked" if bc.is_linked else "const%s" % (
                tuple(round(c, 2) for c in bc.default_value[:3]),)
    sp = spans.get(i)
    span = "u %.3f-%.3f v %.3f-%.3f" % (sp[0][0], sp[1][0], sp[0][1], sp[1][1]) if sp else "-"
    print("%3d %6d   %-30s %-5s %-4s %-10s %s"
          % (i, n, name[:30], has_nodes, bool(bsdf), linked, span))
