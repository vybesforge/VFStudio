"""Swap a head-only reconstruction onto a full body, with visual iteration.

Alignment uses measured bands, not anatomy textbook numbers:
  * body head width measured over the top 12% of stature (above that, shoulders)
  * bust head width measured over the 10-20% band below the crown (above that,
    the messy bun's flyaways spread the silhouette)
  * chin line = where the body's silhouette widens past 1.6x its head width

All three numbers can be overridden on the command line for iteration:
  ... -- body.glb head.glb out.glb [scale] [dz] [chin_frac] [bust_keep_frac]

blender -b --python merge_head2.py -- body.glb head.glb out.glb
"""
import sys

import bmesh
import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
BODY, HEAD, OUT = argv[0], argv[1], argv[2]
def num(i, default=None):
    if len(argv) <= i:
        return default
    v = argv[i].strip().lower()
    if v in ("", "auto", "-"):
        return default
    return float(v)


SCALE_OVR = num(3)
DZ_OVR = num(4)
CHIN_FRAC = num(5, 0.20)
BUST_KEEP = num(6, 0.45)


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


def band_width(obj, frac_top, frac_bot):
    """Width and X/Y centre of the slab between two fractions-below-crown."""
    _, _, (_, zmax) = bounds(obj)
    pts = [obj.matrix_world @ v.co for v in obj.data.vertices]
    zmin = min(p.z for p in pts)
    H = zmax - zmin
    z_hi = zmax - H * frac_top
    z_lo = zmax - H * frac_bot
    sel = [p for p in pts if z_lo <= p.z <= z_hi]
    if len(sel) < 6:
        return None
    xs = [p.x for p in sel]; ys = [p.y for p in sel]
    return (max(xs) - min(xs), (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2)


def cut(obj, z_cut, keep_above):
    bm = bmesh.new(); bm.from_mesh(obj.data)
    mw = obj.matrix_world
    dead = [v for v in bm.verts if ((mw @ v.co).z < z_cut if keep_above
                                    else (mw @ v.co).z > z_cut)]
    bmesh.ops.delete(bm, geom=dead, context="VERTS")
    bm.to_mesh(obj.data); bm.free(); obj.data.update()
    return len(obj.data.vertices)


bpy.ops.wm.read_factory_settings(use_empty=True)
body = import_one(BODY)
_, _, bz = bounds(body)
H = bz[1] - bz[0]
bhead = band_width(body, 0.02, 0.12)
print(f"[body] stature {H:.3f}  head band width {bhead[0]:.3f} centre=({bhead[1]:.3f},{bhead[2]:.3f})")

head = import_one(HEAD)
_, _, hz = bounds(head)
bust = band_width(head, 0.10, 0.20)
print(f"[bust] bbox {hz[1]-hz[0]:.3f} tall  head band width {bust[0]:.3f}")

scale = SCALE_OVR if SCALE_OVR else bhead[0] / bust[0]
head.scale = (scale, scale, scale)
bpy.context.view_layer.update()
_, _, hz2 = bounds(head)
bust2 = band_width(head, 0.10, 0.20)
print(f"[fit] scale {scale:.4f} -> bust {hz2[1]-hz2[0]:.3f} tall")

dx = bhead[1] - bust2[1]
dy = bhead[2] - bust2[2]
dz = (bz[1] - hz2[1]) + (DZ_OVR or 0.0)
head.location = (dx, dy, dz)
bpy.context.view_layer.update()
print(f"[fit] offset ({dx:.3f},{dy:.3f},{dz:.3f})")

chin = bz[1] - H * CHIN_FRAC
print(f"[cut] body below chin z={chin:.3f} -> {cut(body, chin, keep_above=False)} verts")

_, _, hz3 = bounds(head)
cut_h = hz3[1] - (hz3[1] - hz3[0]) * BUST_KEEP
print(f"[cut] bust above z={cut_h:.3f} -> {cut(head, cut_h, keep_above=True)} verts")

for o in bpy.context.scene.objects:
    o.select_set(o.type == "MESH")
bpy.context.view_layer.objects.active = body
bpy.ops.object.join()
merged = bpy.context.view_layer.objects.active
bpy.ops.export_scene.gltf(filepath=OUT, export_format="GLB", use_selection=False)
print(f"[out] {OUT} verts={len(merged.data.vertices)} faces={len(merged.data.polygons)}")
