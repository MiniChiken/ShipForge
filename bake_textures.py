"""Bake the Venator's 27 per-material texture sets into one EVE-style atlas.

The source model gives each material its own 0-1 UV space and its own 2K/4K
maps. An EVE hull area samples ONE set of maps, so everything has to be
re-unwrapped into a single atlas and the original materials baked into it.

The gr2 must then be rebuilt using the ATLAS uv layer, not the original one -
otherwise the geometry and the textures disagree.

Run: blender --background <file>.blend --python bake_textures.py -- <outdir> [size]
"""
import os
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OUT = argv[0] if argv else "."
SIZE = int(argv[1]) if len(argv) > 1 else 2048
ATLAS_UV = "atlas"

scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.samples = 8
scene.cycles.use_denoising = False
scene.render.bake.use_selected_to_active = False
scene.render.bake.margin = 8

# --- join everything ------------------------------------------------------
bpy.ops.object.select_all(action="DESELECT")
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
for o in meshes:
    o.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]
bpy.ops.object.convert(target="MESH")
bpy.ops.object.join()
obj = bpy.context.view_layer.objects.active
print("joined: %d verts %d polys %d materials"
      % (len(obj.data.vertices), len(obj.data.polygons), len(obj.data.materials)))

# --- new atlas UV ---------------------------------------------------------
me = obj.data
SOURCE_UV = me.uv_layers[0].name
if ATLAS_UV in me.uv_layers:
    me.uv_layers.remove(me.uv_layers[ATLAS_UV])
me.uv_layers.new(name=ATLAS_UV)
me.uv_layers.active = me.uv_layers[ATLAS_UV]
me.uv_layers[ATLAS_UV].active_render = True

# Do NOT smart-project: 134k polys shatters into microscopic islands and the
# atlas comes out empty. Each source material already has a clean 0-1 layout,
# so tile those layouts into an NxN grid instead - the mapping is preserved and
# only the scale changes.
import math

nmat = max(1, len(me.materials))
GRID = int(math.ceil(math.sqrt(nmat)))
print("packing %d materials into a %dx%d grid" % (nmat, GRID, GRID))

src = me.uv_layers[0].data
dst = me.uv_layers[ATLAS_UV].data
step = 1.0 / GRID
inset = 0.002          # keeps bleed from neighbouring cells out
for poly in me.polygons:
    mi = min(poly.material_index, nmat - 1)
    col, row = mi % GRID, mi // GRID
    for li in poly.loop_indices:
        u, v = src[li].uv
        u = min(max(u % 1.0 if (u < 0.0 or u > 1.0) else u, 0.0), 1.0)
        v = min(max(v % 1.0 if (v < 0.0 or v > 1.0) else v, 0.0), 1.0)
        dst[li].uv = ((col + inset + u * (1.0 - 2 * inset)) * step,
                      (row + inset + v * (1.0 - 2 * inset)) * step)
print("atlas UV built (grid packing)")


def pin_textures_to_source_uv(source_uv):
    """Force every Image Texture to sample from the ORIGINAL uv layer.

    Texture nodes with an unlinked Vector input sample from whichever layer is
    active_render - which is the ATLAS during baking. That made every source
    texture get read at atlas coordinates instead of its own, so the bakes
    captured scaled/offset garbage and the normal bake came out flat (std ~2 vs
    stock ~20-30). Pinning with explicit UVMap nodes decouples sampling from the
    bake target.
    """
    added = 0
    for mat in me.materials:
        if mat is None or not mat.use_nodes:
            continue
        nt = mat.node_tree
        for node in list(nt.nodes):
            if node.type != "TEX_IMAGE":
                continue
            vec = node.inputs.get("Vector")
            if vec is None or vec.is_linked:
                continue
            uvn = nt.nodes.new("ShaderNodeUVMap")
            uvn.uv_map = source_uv
            nt.links.new(vec, uvn.outputs["UV"])
            added += 1
    print("pinned %d texture nodes to uv layer %r" % (added, source_uv))


def make_image(name):
    img = bpy.data.images.new(name, SIZE, SIZE, alpha=True, float_buffer=False)
    return img


def target_all_materials(img):
    """Every material needs an active image node pointing at the bake target."""
    nodes_added = []
    for mat in me.materials:
        if mat is None or not mat.use_nodes:
            continue
        n = mat.node_tree.nodes.new("ShaderNodeTexImage")
        n.image = img
        n.select = True
        mat.node_tree.nodes.active = n
        nodes_added.append((mat, n))
    return nodes_added


def cleanup(nodes_added):
    for mat, n in nodes_added:
        mat.node_tree.nodes.remove(n)


def bake(pass_type, filename, colorspace="sRGB", **kw):
    img = make_image(filename)
    img.colorspace_settings.name = colorspace
    added = target_all_materials(img)
    try:
        bpy.ops.object.bake(type=pass_type, **kw)
    except Exception as e:
        print("  BAKE FAILED %s: %s" % (filename, e))
        cleanup(added)
        return None
    cleanup(added)
    path = os.path.join(OUT, filename + ".png")
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    print("  baked %s -> %s" % (pass_type, path))
    return path


def bake_basecolor(filename):
    """Bake raw Base Color, not the diffuse response.

    A DIFFUSE bake returns BLACK for anything metallic - metals have no diffuse
    albedo in Cycles - which punches holes wherever the source uses metal. The
    standard workaround is to route Base Color through an Emission shader and
    bake EMIT, which captures the albedo regardless of the metallic value.
    """
    saved = []
    for mat in me.materials:
        if mat is None or not mat.use_nodes:
            continue
        nt = mat.node_tree
        out = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"), None)
        bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if out is None or bsdf is None or not out.inputs["Surface"].is_linked:
            continue
        orig_from = out.inputs["Surface"].links[0].from_socket
        emit = nt.nodes.new("ShaderNodeEmission")
        bc = bsdf.inputs["Base Color"]
        if bc.is_linked:
            nt.links.new(emit.inputs["Color"], bc.links[0].from_socket)
        else:
            emit.inputs["Color"].default_value = bc.default_value
        nt.links.new(out.inputs["Surface"], emit.outputs["Emission"])
        saved.append((mat, out, orig_from, emit))

    path = bake("EMIT", filename, "sRGB")

    for mat, out, orig_from, emit in saved:
        mat.node_tree.links.new(out.inputs["Surface"], orig_from)
        mat.node_tree.nodes.remove(emit)
    return path


def bake_input(input_name, filename):
    """Bake a scalar Principled input (Metallic, etc.) via the Emission trick.

    Blender has no bake pass for Metallic, so route the input into an Emission
    shader and bake EMIT. Needed to drive EVE's material map, which selects
    among the faction's material slots - a flat value makes the whole hull one
    material and kills all specular variation.
    """
    saved = []
    for mat in me.materials:
        if mat is None or not mat.use_nodes:
            continue
        nt = mat.node_tree
        out = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"), None)
        bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if out is None or bsdf is None or not out.inputs["Surface"].is_linked:
            continue
        if input_name not in bsdf.inputs:
            continue
        orig_from = out.inputs["Surface"].links[0].from_socket
        emit = nt.nodes.new("ShaderNodeEmission")
        src = bsdf.inputs[input_name]
        if src.is_linked:
            nt.links.new(emit.inputs["Color"], src.links[0].from_socket)
        else:
            v = src.default_value
            emit.inputs["Color"].default_value = (v, v, v, 1.0)
        nt.links.new(out.inputs["Surface"], emit.outputs["Emission"])
        saved.append((mat, out, orig_from, emit))
    path = bake("EMIT", filename, "Non-Color")
    for mat, out, orig_from, emit in saved:
        mat.node_tree.links.new(out.inputs["Surface"], orig_from)
        mat.node_tree.nodes.remove(emit)
    return path


pin_textures_to_source_uv(SOURCE_UV)

print("baking at %dx%d ..." % (SIZE, SIZE))
bake_basecolor("venator_a")
bake_input("Metallic", "venator_metal")
bake("NORMAL", "venator_n", "Non-Color")
bake("ROUGHNESS", "venator_r", "Non-Color")
bake("EMIT", "venator_g", "sRGB")

# Save the atlas-UV mesh so the geometry export uses the SAME uv layer the
# textures were baked into - otherwise model and textures disagree.
blend_out = os.path.join(OUT, "venator_atlas.blend")
me.uv_layers.active = me.uv_layers[ATLAS_UV]
for i, layer in enumerate(me.uv_layers):
    layer.active_render = (layer.name == ATLAS_UV)
bpy.ops.wm.save_as_mainfile(filepath=blend_out)
print("saved %s" % blend_out)
print("done")
