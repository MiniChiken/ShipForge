"""Composite source textures directly into the atlas - no Cycles baking.

The atlas packing is a plain NxN grid of each material's original 0-1 UV space,
so a material's own texture can be copied straight into its cell. That
sidesteps baking entirely, which matters because Cycles' NORMAL pass was
returning a flat map (std ~2 vs stock ~20-30) and losing all the surface detail
the model actually ships.

Run: blender --background venator_atlas.blend --python composite_atlas.py -- <outdir> [size]
"""
import math
import os
import sys

import numpy as np

import bpy

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OUT = argv[0] if argv else "."
SIZE = int(argv[1]) if len(argv) > 1 else 4096

obj = next(o for o in bpy.data.objects if o.type == "MESH")
me = obj.data
mats = list(me.materials)
GRID = int(math.ceil(math.sqrt(max(1, len(mats)))))
CELL = SIZE // GRID
print("compositing %d materials into %dx%d grid, cell %dpx" % (len(mats), GRID, GRID, CELL))

# which Principled input feeds each output map
CHANNELS = {
    "a": ("Base Color", (190, 190, 190, 255)),
    "n": ("Normal", (128, 128, 255, 255)),
    "r": ("Roughness", (219, 219, 219, 255)),
    "metal": ("Metallic", (0, 0, 0, 255)),
    "g": ("Emission Color", (0, 0, 0, 255)),
}


def image_for(mat, input_name):
    """Find the Image feeding a Principled input, through a Normal Map node if present."""
    if mat is None or not mat.use_nodes:
        return None
    bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        return None
    inp = bsdf.inputs.get(input_name)
    if inp is None or not inp.is_linked:
        return None
    node = inp.links[0].from_node
    if node.type == "NORMAL_MAP":
        cin = node.inputs.get("Color")
        if cin is None or not cin.is_linked:
            return None
        node = cin.links[0].from_node
    while node.type not in ("TEX_IMAGE",):
        nxt = None
        for i in node.inputs:
            if i.is_linked:
                nxt = i.links[0].from_node
                break
        if nxt is None:
            return None
        node = nxt
    return getattr(node, "image", None)


def pixels_of(img, cell):
    """Image -> uint8 RGBA array resized to cell x cell (nearest, numpy only)."""
    w, h = img.size
    if w == 0 or h == 0 or not img.has_data:
        return None
    buf = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(buf)
    a = buf.reshape(h, w, 4)
    a = np.flipud(a)                       # Blender origin is bottom-left
    ys = (np.arange(cell) * (h / cell)).astype(np.int32).clip(0, h - 1)
    xs = (np.arange(cell) * (w / cell)).astype(np.int32).clip(0, w - 1)
    a = a[ys][:, xs]
    if img.colorspace_settings.name == "sRGB":
        rgb = a[..., :3]
    else:
        rgb = a[..., :3]
    return (np.clip(rgb, 0, 1) * 255).astype(np.uint8), (np.clip(a[..., 3], 0, 1) * 255).astype(np.uint8)


for suffix, (input_name, fill) in CHANNELS.items():
    atlas = np.zeros((SIZE, SIZE, 4), np.uint8)
    atlas[..., 0], atlas[..., 1], atlas[..., 2], atlas[..., 3] = fill
    filled = 0
    for mi, mat in enumerate(mats):
        img = image_for(mat, input_name)
        if img is None:
            continue
        got = pixels_of(img, CELL)
        if got is None:
            continue
        rgb, alpha = got
        col, row = mi % GRID, mi // GRID
        # atlas row 0 is the TOP of the image but v=0 is the BOTTOM in UV space
        y0 = SIZE - (row + 1) * CELL
        x0 = col * CELL
        atlas[y0:y0 + CELL, x0:x0 + CELL, :3] = rgb
        atlas[y0:y0 + CELL, x0:x0 + CELL, 3] = 255
        filled += 1
    # Write a raw .npy and convert to PNG outside Blender - saving through
    # bpy.data.images produced all-zero files.
    path = os.path.join(OUT, "venator_%s.npy" % suffix)
    np.save(path, atlas)
    print("  %-6s <- %2d/%d materials  std=%.1f -> %s"
          % (suffix, filled, len(mats), atlas[..., :3].std(), path))
print("done")
