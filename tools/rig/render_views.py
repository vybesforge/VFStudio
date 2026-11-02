"""Render orthographic reference views of a GLB for landmark picking.

Run by `auto_joints.py` (or by hand) through `bin/blender`:

  blender -b --python tools/rig/render_views.py -- <src.glb> <outdir> [res]

Writes <outdir>/{px,nx,py,ny,top}.png plus <outdir>/views.json. The manifest carries,
per view, the exact linear map from Blender world XYZ to pixel coordinates (measured
with world_to_camera_view, so it cannot drift from what was rendered) and the camera
axis. `auto_joints.py` inverts that to turn image-space joint guesses into 3D.

Workbench renderer on purpose: flat studio shading + cavity, no textures, no lighting
noise — the silhouette and the limb creases are what a vision model needs to see.

Blender imports glTF Y-up as Z-up: blender (x, y, z) == gltf (x, z, -y).
"""
import json
import os
import sys

import bpy
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
SRC, OUT = argv[0], argv[1]
RES = int(argv[2]) if len(argv) > 2 else 768
os.makedirs(OUT, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SRC)

meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
if not meshes:
    sys.exit("no mesh in GLB")

corners = []
for o in meshes:
    for c in o.bound_box:
        corners.append(o.matrix_world @ Vector(c))
mn = Vector((min(p.x for p in corners), min(p.y for p in corners), min(p.z for p in corners)))
mx = Vector((max(p.x for p in corners), max(p.y for p in corners), max(p.z for p in corners)))
size = mx - mn
center = (mn + mx) * 0.5
span = max(size.x, size.y, size.z)

scene = bpy.context.scene
scene.render.engine = "BLENDER_WORKBENCH"
scene.render.resolution_x = scene.render.resolution_y = RES
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.film_transparent = False
try:
    sh = scene.display.shading
    sh.light = "STUDIO"
    sh.color_type = "SINGLE"
    sh.single_color = (0.62, 0.64, 0.68)
    sh.show_cavity = True
    sh.cavity_type = "BOTH"
    sh.show_object_outline = False
except Exception as exc:          # renderer changed between Blender versions
    print(f"[views] workbench shading tuning skipped: {exc}")

# Camera on +axis looking back at the model. The second argument is the camera's LOCAL up
# axis, which must be 'Y' for every view: passing 'Z' collides with the track axis and
# Blender then picks an arbitrary roll, which is how the rear view ended up upside down.
VIEWS = [("px", Vector((1, 0, 0)), "Y"), ("nx", Vector((-1, 0, 0)), "Y"),
         ("py", Vector((0, 1, 0)), "Y"), ("ny", Vector((0, -1, 0)), "Y"),
         ("top", Vector((0, 0, 1)), "Y")]

manifest = {"src": os.path.abspath(SRC), "res": RES, "views": [],
            "bbox": {"min": list(mn), "max": list(mx)}, "span": span}
probes = [Vector((0, 0, 0)), Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))]

for name, axis, up in VIEWS:
    cam_data = bpy.data.cameras.new(name)
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = span * 1.12
    # a roll flip moves the pixel map with the image, but the manifest is measured from
    # world_to_camera_view, so the map stays correct either way; upright only matters to
    # the vision model, which reads orientation from the picture.
    cam = bpy.data.objects.new(name, cam_data)
    scene.collection.objects.link(cam)
    cam.location = center + axis * (span * 3.0)
    cam.rotation_euler = (-axis).to_track_quat("-Z", up).to_euler()
    scene.camera = cam
    bpy.context.view_layer.update()

    uv = []
    for p in probes:
        c = world_to_camera_view(scene, cam, mn + p)
        uv.append((c.x * RES, (1.0 - c.y) * RES))       # pixels, origin top-left
    path = os.path.join(OUT, f"{name}.png")
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)

    manifest["views"].append({
        "name": name,
        "file": os.path.basename(path),
        "axis": list(axis),                 # camera sits on +axis, looks along -axis
        "origin": list(mn),
        "u": [uv[1][0] - uv[0][0], uv[2][0] - uv[0][0], uv[3][0] - uv[0][0]],
        "v": [uv[1][1] - uv[0][1], uv[2][1] - uv[0][1], uv[3][1] - uv[0][1]],
        "u0": uv[0][0], "v0": uv[0][1],
    })
    print(f"[views] {name}: scale={cam_data.ortho_scale:.3f} -> {path}")

with open(os.path.join(OUT, "views.json"), "w") as fh:
    json.dump(manifest, fh, indent=1)
print(f"[views] wrote {os.path.join(OUT, 'views.json')} (span {span:.3f})")
