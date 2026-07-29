"""Export the evaluated Venator geometry to glTF as a neutral intermediate.

The .blend carries 21 Geometry Nodes modifiers, so raw mesh datablocks are NOT
the final geometry - everything must go through the evaluated depsgraph.
glTF is used as the intermediate because it preserves per-vertex normals, UVs,
tangents and per-material primitive groups, which is exactly the set the gr2
hull needs.

Run: blender --background <file>.blend --python export_mesh.py -- <out.glb>
"""
import sys
import bpy

out = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else "venator.glb"

deps = bpy.context.evaluated_depsgraph_get()

raw_v = raw_t = ev_v = ev_t = 0
for o in [x for x in bpy.data.objects if x.type == "MESH"]:
    m = o.data
    raw_v += len(m.vertices)
    raw_t += sum(len(p.vertices) - 2 for p in m.polygons)
    ev = o.evaluated_get(deps)
    em = ev.to_mesh()
    ev_v += len(em.vertices)
    ev_t += sum(len(p.vertices) - 2 for p in em.polygons)
    ev.to_mesh_clear()

print("RAW       vertices=%d triangles=%d" % (raw_v, raw_t))
print("EVALUATED vertices=%d triangles=%d" % (ev_v, ev_t))
print("DELTA     vertices=%+d triangles=%+d" % (ev_v - raw_v, ev_t - raw_t))

bpy.ops.export_scene.gltf(
    filepath=out,
    export_format="GLB",
    use_selection=False,
    export_apply=True,          # evaluate modifiers, incl. geometry nodes
    export_normals=True,
    export_tangents=True,
    export_texcoords=True,
    export_materials="EXPORT",
    export_yup=True,
)
print("WROTE %s" % out)
