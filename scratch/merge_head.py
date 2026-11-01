"""Swap a separately-reconstructed head onto the body, cutting both at the neck.

Why: a full-body recon gives the face ~5% of a 4096 atlas, so eyes come out as
voids. A head-only recon gives the face the whole atlas. Neither mesh is a clean
quad topology (they are ~1500-island soup), so this never tries to bridge loops —
it measures the neck on each, deletes the discarded side, and overlaps the two
shells at the cut so the seam hides under the jaw.

blender -b --python merge_head.py -- body.glb head.glb out.glb
"""
import sys

import bmesh
import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
BODY, HEAD, OUT = argv[0], argv[1], argv[2]


def load(path):
    # NOTE: never read_factory_settings here — it would wipe the previously
    # imported mesh. Reset once in main(), then import each file into the scene.
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


def slice_stats(obj, z0, z1, n=120):
    """Width/depth/centre per horizontal slab, in world space."""
    mw = obj.matrix_world
    zs = [(mw @ v.co).z for v in obj.data.vertices]
    lo, hi = min(zs), max(zs)
    if z0 is None:
        z0, z1 = lo, hi
    span = (z1 - z0) / n
    bins = [[] for _ in range(n)]
    for v in obj.data.vertices:
        w = mw @ v.co
        i = int((w.z - z0) / span) if span else 0
        if 0 <= i < n:
            bins[i].append(w)
    out = []
    for i, pts in enumerate(bins):
        if len(pts) < 8:
            out.append(None)
            continue
        xs = [p.x for p in pts]
        ys = [p.y for p in pts]
        out.append({
            "z": z0 + (i + 0.5) * span,
            "w": max(xs) - min(xs),
            "d": max(ys) - min(ys),
            "cx": (max(xs) + min(xs)) / 2,
            "cy": (max(ys) + min(ys)) / 2,
            "n": len(pts),
        })
    return out, lo, hi


def find_neck(obj, from_top=0.45):
    """Neck = narrowest slab between the shoulders and the crown."""
    zs = [(obj.matrix_world @ v.co).z for v in obj.data.vertices]
    lo, hi = min(zs), max(zs)
    z0 = hi - (hi - lo) * from_top
    st, _, _ = slice_stats(obj, z0, hi, n=140)
    st = [s for s in st if s]
    if not st:
        sys.exit("no slabs")
    shoulder = max(st, key=lambda s: s["w"])
    above = [s for s in st if s["z"] > shoulder["z"]]
    if not above:
        above = st[-10:]
    neck = min(above, key=lambda s: s["w"])
    return neck, shoulder, lo, hi


def cut(obj, z_cut, keep_above):
    me = obj.data
    bm = bmesh.new()
    bm.from_mesh(me)
    mw = obj.matrix_world
    dead = [v for v in bm.verts if (mw @ v.co).z < z_cut] if keep_above else \
           [v for v in bm.verts if (mw @ v.co).z > z_cut]
    bmesh.ops.delete(bm, geom=dead, context="VERTS")
    bm.to_mesh(me)
    bm.free()
    me.update()
    return len(me.vertices)


bpy.ops.wm.read_factory_settings(use_empty=True)
body = load(BODY)
bn, bs, blo, bhi = find_neck(body)
print(f"[body] neck     z={bn['z']:.3f} w={bn['w']:.3f} centre=({bn['cx']:.3f},{bn['cy']:.3f})")
body_head_h = bhi - bn["z"]

head = load(HEAD)
hn, hs, hlo, hhi = find_neck(head)
print(f"[head] height {hhi - hlo:.3f}  shoulders z={hs['z']:.3f} w={hs['w']:.3f}")
print(f"[head] neck     z={hn['z']:.3f} w={hn['w']:.3f} centre=({hn['cx']:.3f},{hn['cy']:.3f})")
head_head_h = hhi - hn["z"]

# Scale so the skull above the neck matches the body's head height. Height beats
# width here because both meshes carry a hair bun that inflates width.
scale = body_head_h / head_head_h if head_head_h else 1.0
print(f"[fit] body head {body_head_h:.3f}  head {head_head_h:.3f}  scale {scale:.4f}")
head.scale = (scale, scale, scale)
bpy.context.view_layer.update()

# Recompute after scaling, then place the head's neck on the body's neck.
hn2, _, hlo2, hhi2 = find_neck(head)
dx = bn["cx"] - hn2["cx"]
dy = bn["cy"] - hn2["cy"]
dz = bn["z"] - hn2["z"]
head.location = (dx, dy, dz)
bpy.context.view_layer.update()
print(f"[fit] offset ({dx:.3f},{dy:.3f},{dz:.3f})")

# Overlap slightly into the body so no gap shows at the jaw line.
cut_z = bn["z"] + (bhi - bn["z"]) * 0.02
kept = cut(body, cut_z, keep_above=False)
print(f"[cut] body kept {kept} verts below z={cut_z:.3f}")

head_cut_z = hn2["z"] + dz - (hhi2 - hn2["z"]) * 0.06
kh = cut(head, head_cut_z, keep_above=True)
print(f"[cut] head kept {kh} verts above z={head_cut_z:.3f}")

for o in bpy.context.scene.objects:
    o.select_set(o.type == "MESH")
bpy.context.view_layer.objects.active = body
bpy.ops.object.join()
merged = bpy.context.view_layer.objects.active
merged.name = "merged"

bpy.ops.wm.save_as_mainfile(filepath="/tmp/merge_head.blend")
bpy.ops.export_scene.gltf(filepath=OUT, export_format="GLB", use_selection=False)
print(f"[out] {OUT} verts={len(merged.data.vertices)} tris={len(merged.data.polygons)}")
