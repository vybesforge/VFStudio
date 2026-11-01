"""Overlay a head-only reconstruction onto a full body without cutting either mesh.

Cutting leaves an open rim that reads as a hard seam ring at the neck. Instead this
encloses the body's own head inside the bust: the bust is scaled a few percent
larger and centred on the body's head, so the visible surface is entirely the
detail head, and the original head becomes hidden interior geometry.

blender -b --python merge_head3.py -- body.glb head.glb out.glb [grow]

`grow` is the enclosure margin (default 1.10, i.e. 10% larger).
"""
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
BODY, HEAD, OUT = argv[0], argv[1], argv[2]
GROW = float(argv[3]) if len(argv) > 3 else 1.10


def import_one(path):
    before = set(bpy.context.scene.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    ms = [o for o in bpy.context.scene.objects if o.type == "MESH" and o not in before]
    for o in ms:
        o.select_set(True)
    bpy.context.view_layer.objects.active = ms[0]
    if len(ms) > 1:
        bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active
    for o in bpy.context.scene.objects:
        o.select_set(False)
    return obj


def bounds(obj):
    pts = [obj.matrix_world @ v.co for v in obj.data.vertices]
    xs = [p.x for p in pts]; ys = [p.y for p in pts]; zs = [p.z for p in pts]
    return (min(xs), max(xs)), (min(ys), max(ys)), (min(zs), max(zs))


def band(obj, frac_top, frac_bot):
    (_, _), (_, _), (_, zmax) = bounds(obj)
    pts = [obj.matrix_world @ v.co for v in obj.data.vertices]
    zmin = min(p.z for p in pts)
    H = zmax - zmin
    sel = [p for p in pts if zmax - H * frac_bot <= p.z <= zmax - H * frac_top]
    if len(sel) < 6:
        return None
    xs = [p.x for p in sel]; ys = [p.y for p in sel]
    return (max(xs) - min(xs), (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2)


bpy.ops.wm.read_factory_settings(use_empty=True)
body = import_one(BODY)
_, _, bz = bounds(body)
H = bz[1] - bz[0]
bhead = band(body, 0.02, 0.12)
print(f"[body] stature {H:.3f}  head width {bhead[0]:.3f} centre=({bhead[1]:.3f},{bhead[2]:.3f})")

head = import_one(HEAD)
_, _, hz = bounds(head)
bust = band(head, 0.10, 0.20)
scale = (bhead[0] / bust[0]) * GROW
head.scale = (scale, scale, scale)
bpy.context.view_layer.update()
_, _, hz2 = bounds(head)
bust2 = band(head, 0.10, 0.20)

# Centre on the body's head and drop the crowns together, then sink it slightly so
# the jaw closes around the neck instead of hovering over it.
dx = bhead[1] - bust2[1]
dy = bhead[2] - bust2[2]
dz = (bz[1] - hz2[1]) - (hz2[1] - hz2[0]) * 0.06
head.location = (dx, dy, dz)
bpy.context.view_layer.update()
print(f"[fit] grow {GROW} scale {scale:.4f}  offset ({dx:.3f},{dy:.3f},{dz:.3f})")

for o in bpy.context.scene.objects:
    o.select_set(o.type == "MESH")
bpy.context.view_layer.objects.active = body
bpy.ops.object.join()
merged = bpy.context.view_layer.objects.active
bpy.ops.export_scene.gltf(filepath=OUT, export_format="GLB", use_selection=False)
print(f"[out] {OUT} verts={len(merged.data.vertices)} faces={len(merged.data.polygons)}")
