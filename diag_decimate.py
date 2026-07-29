"""Measure whether decimation is punching holes in the hull.

The base LOD is decimated to ~18% to fit 16-bit indices. Collapse decimation on
hard-surface panel geometry can tear it open. Boundary edges (edges used by
exactly one face) are the signal: a closed shell has none, and holes create
them.

Run: blender --background venator_atlas.blend --python diag_decimate.py
"""
import bpy


def stats(obj, ratio, dtype="COLLAPSE", angle=0.087):
    for m in list(obj.modifiers):
        obj.modifiers.remove(m)
    if ratio < 1.0 or dtype != "COLLAPSE":
        d = obj.modifiers.new("dec", "DECIMATE")
        d.decimate_type = dtype
        if dtype == "COLLAPSE":
            d.ratio = ratio
        else:
            d.angle_limit = angle
    deps = bpy.context.evaluated_depsgraph_get()
    me = obj.evaluated_get(deps).to_mesh()
    me.calc_loop_triangles()
    counts = {}
    for e in me.edges:
        counts[e.key] = 0
    for poly in me.polygons:
        vs = list(poly.vertices)
        for i in range(len(vs)):
            k = tuple(sorted((vs[i], vs[(i + 1) % len(vs)])))
            counts[k] = counts.get(k, 0) + 1
    boundary = sum(1 for v in counts.values() if v == 1)
    nonman = sum(1 for v in counts.values() if v > 2)
    res = (len(me.vertices), len(me.loop_triangles), boundary, nonman)
    obj.evaluated_get(deps).to_mesh_clear()
    return res


obj = next(o for o in bpy.data.objects if o.type == "MESH")
print("%-26s %8s %8s %9s %9s" % ("config", "verts", "tris", "boundary", "nonmanif"))
for label, ratio, dtype in [
        ("original", 1.0, "COLLAPSE"),
        ("collapse 0.50", 0.50, "COLLAPSE"),
        ("collapse 0.1822 (current)", 0.1822, "COLLAPSE"),
        ("planar dissolve 5deg", 1.0, "DISSOLVE"),
]:
    v, t, b, nm = stats(obj, ratio, dtype)
    print("%-26s %8d %8d %9d %9d" % (label, v, t, b, nm))
