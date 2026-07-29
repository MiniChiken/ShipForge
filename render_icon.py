"""Render the ship icons the client looks for.

Icons resolve as <graphicIDs[gid].iconInfo.folder>/<graphicID>_<size>, e.g.
res:/dx9/model/ship/minmatar/battleship/mb3/icons/3134_64.png. Our graphicID
record inherited the Maelstrom's folder, so the client was asking for
900001_64.png inside a stock folder that has no such file - hence no icon.

Renders 64/128 PNG with alpha and a 512 JPG on a dark plate, matching the
shipped set. Workbench with studio lighting is deliberate: it needs no light
rig and cannot produce the black-panel results the PBR materials gave earlier.

Run: blender --background <file>.blend --python render_icon.py -- <out dir>
"""
import os
import sys

import bpy
from mathutils import Vector

OUT = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else "icons"
GRAPHIC_ID = 900001

os.makedirs(OUT, exist_ok=True)

meshes = [o for o in bpy.data.objects if o.type == "MESH"]
lo = Vector((1e30,) * 3)
hi = Vector((-1e30,) * 3)
for o in meshes:
    for c in o.bound_box:
        w = o.matrix_world @ Vector(c)
        lo = Vector((min(lo.x, w.x), min(lo.y, w.y), min(lo.z, w.z)))
        hi = Vector((max(hi.x, w.x), max(hi.y, w.y), max(hi.z, w.z)))
centre = (lo + hi) * 0.5
size = max(hi - lo)

scene = bpy.context.scene
scene.render.engine = "BLENDER_WORKBENCH"
scene.display.shading.light = "STUDIO"
scene.display.shading.color_type = "TEXTURE"
scene.display.shading.show_shadows = True
scene.display.shading.show_cavity = True
scene.display.render_aa = "16"

# Three-quarter view from above and ahead. The nose points along Blender -Y
# (EVE +Z forward maps to Blender -Y), so the camera sits on the -Y side.
direction = Vector((0.80, -1.00, 0.55)).normalized()
camera_data = bpy.data.cameras.new("icon_cam")
camera_data.type = "ORTHO"
camera_data.ortho_scale = size * 1.06
camera = bpy.data.objects.new("icon_cam", camera_data)
scene.collection.objects.link(camera)
camera.location = centre + direction * size * 3.0
camera.rotation_euler = direction.to_track_quat("Z", "Y").to_euler()
scene.camera = camera


def render(path, width, height, transparent, fmt):
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = transparent
    scene.render.image_settings.file_format = fmt
    if fmt == "PNG":
        scene.render.image_settings.color_mode = "RGBA"
    else:
        scene.render.image_settings.color_mode = "RGB"
        scene.render.image_settings.quality = 92
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    print("rendered %s (%dx%d)" % (path, width, height))


base = os.path.join(OUT, str(GRAPHIC_ID))
render(base + "_64.png", 64, 64, True, "PNG")
render(base + "_128.png", 128, 128, True, "PNG")
# the 512 is a JPG in the shipped set, so it needs an opaque plate
scene.display.shading.background_type = "VIEWPORT"
scene.display.shading.background_color = (0.02, 0.03, 0.04)
render(base + "_512.jpg", 512, 512, False, "JPEG")
print("done")
