"""Build the emissive (_g) atlas from the model's own light-emitting materials.

The composited glow atlas came out at mean 0.0 - completely black - because none
of the source materials link anything into Principled "Emission Color". The model
does however have a dedicated `Windows` material (and `Thruster Glow`), so the
emissive can be derived from those materials' own Base Color instead of invented.

A black _g is a large part of why the hull reads as dark: nothing on it emits, so
the ship only ever shows reflected scene light.

Packing matches composite_atlas.py exactly - a material's cell is
(mi % GRID, mi // GRID) over the joined mesh's material list - so this writes
into the same cells the geometry's atlas UVs already sample.

Run: blender --background venator_atlas.blend --python make_glow_map.py -- <outdir> [size]
"""
import math
import os
import sys

import numpy as np

import bpy

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OUT = argv[0] if argv else "."
SIZE = int(argv[1]) if len(argv) > 1 else 4096

# material name prefix -> emissive gain. Windows are the hull's running lights;
# the thruster glow discs already have boosters on them, but a little emissive
# keeps the nozzles from reading as flat grey when the engines are idle.
GLOW_MATERIALS = {"Windows": 1.0, "Thruster Glow": 0.65}

obj = next(o for o in bpy.data.objects if o.type == "MESH")
mats = list(obj.data.materials)
GRID = int(math.ceil(math.sqrt(max(1, len(mats)))))
CELL = SIZE // GRID
print("glow atlas: %d materials, %dx%d grid, cell %dpx" % (len(mats), GRID, GRID, CELL))


def image_for(mat, input_name):
    if mat is None or not mat.use_nodes:
        return None
    bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        return None
    inp = bsdf.inputs.get(input_name)
    if inp is None or not inp.is_linked:
        return None
    node = inp.links[0].from_node
    while node.type != "TEX_IMAGE":
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
    w, h = img.size
    if w == 0 or h == 0 or not img.has_data:
        return None
    buf = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(buf)
    a = np.flipud(buf.reshape(h, w, 4))       # Blender origin is bottom-left
    ys = (np.arange(cell) * (h / cell)).astype(np.int32).clip(0, h - 1)
    xs = (np.arange(cell) * (w / cell)).astype(np.int32).clip(0, w - 1)
    return np.clip(a[ys][:, xs][..., :3], 0, 1)


atlas = np.zeros((SIZE, SIZE, 4), np.uint8)
atlas[..., 3] = 255
filled = []
for mi, mat in enumerate(mats):
    if mat is None:
        continue
    gain = next((g for name, g in GLOW_MATERIALS.items()
                 if mat.name.startswith(name)), None)
    if gain is None:
        continue
    rgb = None
    img = image_for(mat, "Base Color")
    if img is not None:
        rgb = pixels_of(img, CELL)
    if rgb is None:
        # No texture on the material - fall back to its flat base colour, so a
        # windows material defined purely by a colour still lights up.
        bsdf = next((n for n in mat.node_tree.nodes
                     if n.type == "BSDF_PRINCIPLED"), None) if mat.use_nodes else None
        base = tuple(bsdf.inputs["Base Color"].default_value)[:3] if bsdf else (1, 1, 1)
        rgb = np.tile(np.array(base, np.float32), (CELL, CELL, 1))

    col, row = mi % GRID, mi // GRID
    y0 = SIZE - (row + 1) * CELL
    x0 = col * CELL
    atlas[y0:y0 + CELL, x0:x0 + CELL, :3] = (np.clip(rgb * gain, 0, 1) * 255).astype(np.uint8)
    filled.append("%s(cell %d,%d gain %.2f)" % (mat.name, col, row, gain))

path = os.path.join(OUT, "venator_g_lit.npy")
np.save(path, atlas)
print("  emissive from: %s" % ", ".join(filled) if filled else "  NOTHING MATCHED")
print("  mean=%.2f  nonzero=%.4f  ->  %s"
      % (atlas[..., :3].mean(), (atlas[..., :3] > 0).mean(), path))
