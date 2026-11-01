"""Overlay a head-only reconstruction onto a full body, without cutting either mesh.

Cutting both meshes at the neck leaves the body's open boundary visible as a hard ring
even when the scales match, because there is no topology to bridge on a ~4,000-island
soup mesh. Enclosure avoids the problem entirely: the detail head is scaled slightly
larger and centred on the body's own head, so the visible surface is all detail head and
the original head becomes hidden interior geometry.

Alignment is measured, never guessed:
  * body head width  = widest slab in the top 12% of stature (above that, shoulders)
  * bust head width  = widest slab in the 10-20% band below the crown (above that, a
    messy bun's flyaways spread the silhouette and inflate a naive width measure)

Usage:
  blender -b --python merge_head_overlay.py -- body.glb head.glb out.glb [grow]

`grow` is the enclosure margin. Start at 1.03: a 10% margin still reads as an oversized
head in a full-body render. Judge the result at TWO framings — head size on the whole
figure, face detail on a head crop.
"""
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
BODY, HEAD, OUT = argv[0], argv[1], argv[2]
GROW = float(argv[3]) if len(argv) > 3 else 1.03


def import_one(path):
    """Import into the CURRENT scene.

    Deliberately does not call read_factory_settings — doing that per file wipes the
    mesh imported before it, and the merge then silently runs on one object.
    """
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
    xs = [p.x for p in pts]
    ys = [p.y for p in pts]
    zs = [p.z for p in pts]
    return (min(xs), max(xs)), (min(ys), max(ys)), (min(zs), max(zs))


def band(obj, frac_top, frac_bot):
    """Width and X/Y centre of the slab between two fractions below the crown."""
    (_, _), (_, _), (_, zmax) = bounds(obj)
    pts = [obj.matrix_world @ v.co for v in obj.data.vertices]
    zmin = min(p.z for p in pts)
    H = zmax - zmin
    sel = [p for p in pts if zmax - H * frac_bot <= p.z <= zmax - H * frac_top]
    if len(sel) < 6:
        return None
    xs = [p.x for p in sel]
    ys = [p.y for p in sel]
    return (max(xs) - min(xs), (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2)


bpy.ops.wm.read_factory_settings(use_empty=True)
body = import_one(BODY)
_, _, bz = bounds(body)
H = bz[1] - bz[0]
bhead = band(body, 0.02, 0.12)
print(f"[body] stature {H:.3f}  head width {bhead[0]:.3f} "
      f"centre=({bhead[1]:.3f},{bhead[2]:.3f})")

head = import_one(HEAD)
_, _, hz = bounds(head)
bust = band(head, 0.10, 0.20)
scale = (bhead[0] / bust[0]) * GROW
head.scale = (scale, scale, scale)
bpy.context.view_layer.update()
_, _, hz2 = bounds(head)
bust2 = band(head, 0.10, 0.20)

# Centre on the body's head, drop the crowns together, then sink slightly so the jaw
# closes around the neck instead of hovering above it.
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
