"""rigify_auto.py — Blender 5.x headless: auto-rig a mesh with Rigify, bake a test animation, export GLB.

Usage (ALWAYS through the wrapper, paths absolute):
  ~/media-stack/bin/blender -b --python ~/media-stack/tools/anim/rigify_auto.py -- \
      --in  /abs/in.glb  --out /abs/out_rigged.glb \
      [--quadruped] [--decimate 100000] [--frames 24] [--fps 24] [--uniform] [--flip] \
      [--length-axis auto|x|y] [--save-blend /abs/out.blend] [--no-anim]

What it does, in order (each step prints a `[rigify_auto]` line):
  1. imports GLB/glTF/FBX/OBJ, deletes any armature/empties it came with, joins all meshes into one
  2. --decimate N: collapses to about N triangles (needed for 700k-tri reconstructions; bone heat
     and glTF export are far faster, and the rig deforms a 100k mesh just as well)
  3. adds a Rigify metarig (human, or "Basic Quadruped" with --quadruped), moves its bones so the
     metarig bounding box matches the mesh bounding box (per-axis; --uniform = height only),
     generates the control rig
  4. parents the mesh to the rig: automatic weights (bone heat) -> if coverage < 98 % of vertices,
     envelope weights -> if still poor, nearest-deform-bone proximity weights (always succeeds).
     Prints which one was used: `[rigify_auto] weights=AUTO|ENVELOPE|PROXIMITY coverage=99.8%`
  5. keyframes a simple cycle on the control bones (torso bob + alternating foot/hand IK stride +
     head nod) over --frames frames
  6. exports a GLB with only the deform bones (DEF-*) as the skin and the baked animation "AutoCycle"

Assumptions: Z up, model faces -Y (Blender/Rigify convention; glTF imports land that way when the
model was authored facing +Z). For quadrupeds the body length is expected along Y; if the mesh is
longer along X it is rotated automatically (--length-axis x|y to force, --flip to turn 180°).
Verify the result with verify_anim_glb.py (vertex displacement through the depsgraph).
"""
import argparse
import math
import os
import sys
import time

import bpy
import numpy as np
from mathutils import Matrix, Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--in", dest="src", required=True)
ap.add_argument("--out", dest="dst", required=True)
ap.add_argument("--quadruped", action="store_true")
ap.add_argument("--decimate", type=int, default=0, help="target triangle count (0 = keep)")
ap.add_argument("--frames", type=int, default=24)
ap.add_argument("--fps", type=int, default=24)
ap.add_argument("--uniform", action="store_true", help="scale metarig uniformly by height only")
ap.add_argument("--flip", action="store_true", help="rotate mesh 180 deg around Z before rigging")
ap.add_argument("--length-axis", default="auto", choices=["auto", "x", "y"])
ap.add_argument("--save-blend", default="")
ap.add_argument("--no-anim", action="store_true")
ap.add_argument("--min-coverage", type=float, default=0.98)
args = ap.parse_args(argv)

T0 = time.time()


def log(msg):
    print(f"[rigify_auto] {msg}", flush=True)


def select_only(*objs, active=None):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = active or objs[0]


# ── 1. import ──────────────────────────────────────────────────────────────
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.preferences.addon_enable(module="rigify")
ext = os.path.splitext(args.src)[1].lower()
if ext in (".glb", ".gltf"):
    bpy.ops.import_scene.gltf(filepath=args.src)
elif ext == ".fbx":
    bpy.ops.import_scene.fbx(filepath=args.src)
elif ext == ".obj":
    bpy.ops.wm.obj_import(filepath=args.src)
else:
    sys.exit(f"unsupported input {ext}")

meshes = [o for o in bpy.data.objects if o.type == "MESH"]
if not meshes:
    sys.exit("no mesh found in input")
# drop armatures / empties / existing animation; keep world transforms of meshes
for o in meshes:
    mw = o.matrix_world.copy()
    o.parent = None
    o.matrix_world = mw
    for m in list(o.modifiers):
        if m.type == "ARMATURE":
            o.modifiers.remove(m)
    o.vertex_groups.clear()
    o.animation_data_clear()
for o in [o for o in bpy.data.objects if o.type != "MESH"]:
    bpy.data.objects.remove(o, do_unlink=True)
for a in list(bpy.data.actions):
    bpy.data.actions.remove(a)
select_only(*meshes, active=meshes[0])
if len(meshes) > 1:
    bpy.ops.object.join()
obj = bpy.context.view_layer.objects.active
obj.name = "Body"
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
log(f"imported {os.path.basename(args.src)}: {len(obj.data.polygons)} faces, {len(obj.data.vertices)} verts, merged {len(meshes)} mesh(es)")

# ── 2. decimate ────────────────────────────────────────────────────────────
if args.decimate and len(obj.data.polygons) > args.decimate:
    ratio = args.decimate / len(obj.data.polygons)
    mod = obj.modifiers.new("Decimate", "DECIMATE")
    mod.ratio = ratio
    select_only(obj)
    bpy.ops.object.modifier_apply(modifier=mod.name)
    log(f"decimated ratio={ratio:.3f} -> {len(obj.data.polygons)} faces ({time.time() - T0:.1f}s)")


def bbox(o):
    """World-space bbox from the vertices (o.bound_box is stale right after transform_apply)."""
    n = len(o.data.vertices)
    co = np.empty(n * 3)
    o.data.vertices.foreach_get("co", co)
    co = co.reshape(n, 3) @ np.array(o.matrix_world.to_3x3().transposed()) + np.array(o.matrix_world.translation)
    return Vector(co.min(axis=0)), Vector(co.max(axis=0))


# ── orientation for quadrupeds: body length along Y ────────────────────────
mn, mx = bbox(obj)
size = mx - mn
rot_z = 0.0
if args.quadruped:
    axis = args.length_axis
    if axis == "auto":
        axis = "x" if size.x > size.y else "y"
    if axis == "x":
        rot_z = -math.pi / 2
if args.flip:
    rot_z += math.pi
if rot_z:
    obj.rotation_mode = "XYZ"  # glTF import leaves QUATERNION mode, where rotation_euler is ignored
    obj.rotation_euler[2] = rot_z
    select_only(obj)
    bpy.ops.object.transform_apply(rotation=True)
    mn, mx = bbox(obj)
    size = mx - mn
    log(f"rotated mesh {math.degrees(rot_z):.0f} deg around Z so length is along Y")
log(f"mesh bbox min={tuple(round(v, 3) for v in mn)} size={tuple(round(v, 3) for v in size)}")

# ── 3. metarig fitted to bbox, generate rig ────────────────────────────────
if args.quadruped:
    bpy.ops.object.armature_basic_quadruped_metarig_add()
else:
    bpy.ops.object.armature_human_metarig_add()
meta = bpy.context.active_object
meta.name = "metarig"
select_only(meta)
bpy.ops.object.mode_set(mode="EDIT")
eb = meta.data.edit_bones
pts = [b.head.copy() for b in eb] + [b.tail.copy() for b in eb]
m_mn = Vector([min(p[i] for p in pts) for i in range(3)])
m_mx = Vector([max(p[i] for p in pts) for i in range(3)])
m_size = m_mx - m_mn
if args.uniform:
    s = size.z / m_size.z
    scale = Vector((s, s, s))
else:
    scale = Vector([size[i] / m_size[i] if m_size[i] > 1e-6 else 1.0 for i in range(3)])
# centre x/y on the mesh, feet on the mesh floor
m_centre = (m_mn + m_mx) * 0.5
centre = (mn + mx) * 0.5


def fit(p):
    return Vector((centre.x + (p.x - m_centre.x) * scale.x,
                   centre.y + (p.y - m_centre.y) * scale.y,
                   mn.z + (p.z - m_mn.z) * scale.z))


for b in eb:
    h, t = fit(b.head), fit(b.tail)
    b.head, b.tail = h, t
    b.envelope_distance *= max(scale)
    b.head_radius *= max(scale)
    b.tail_radius *= max(scale)
bpy.ops.object.mode_set(mode="OBJECT")
log(f"metarig {'quadruped' if args.quadruped else 'human'} scaled by {tuple(round(v, 2) for v in scale)}")

select_only(meta)
bpy.ops.pose.rigify_generate()
rig = bpy.data.objects.get(meta.data.rigify_target_rig.name if meta.data.rigify_target_rig else "rig")
if rig is None:
    rig = next(o for o in bpy.data.objects if o.type == "ARMATURE" and o is not meta)
rig.name = "rig"
def_bones = [b.name for b in rig.data.bones if b.use_deform]
log(f"rigify generated: {len(rig.data.bones)} bones, {len(def_bones)} deform ({time.time() - T0:.1f}s)")
meta.hide_set(True)

# ── 4. weights with fallbacks ──────────────────────────────────────────────


def coverage(o):
    """Fraction of vertices with any weight > 1e-5 in a deform-bone group."""
    idx = {vg.index for vg in o.vertex_groups if vg.name in def_bones}
    n = 0
    for v in o.data.vertices:
        if any(g.group in idx and g.weight > 1e-5 for g in v.groups):
            n += 1
    return n / max(1, len(o.data.vertices))


def clear_bind(o):
    for m in list(o.modifiers):
        if m.type == "ARMATURE":
            o.modifiers.remove(m)
    o.vertex_groups.clear()
    mw = o.matrix_world.copy()
    o.parent = None
    o.matrix_world = mw


def try_bind(kind):
    clear_bind(obj)
    select_only(obj, rig, active=rig)
    try:
        bpy.ops.object.parent_set(type=kind)
    except Exception as exc:
        log(f"{kind} raised: {exc}")
        return 0.0
    return coverage(obj)


def proximity_weights(o, armature, bones, k=2):
    """Nearest-deform-bone binding (blend of k nearest segments, inverse-distance)."""
    clear_bind(o)
    co = np.array([v.co[:] for v in o.data.vertices], dtype=np.float64)
    names, segs = [], []
    for name in bones:
        b = armature.data.bones[name]
        names.append(name)
        segs.append((np.array((armature.matrix_world @ b.head_local)[:]),
                     np.array((armature.matrix_world @ b.tail_local)[:])))
    d = np.empty((len(co), len(names)))
    for j, (a, b_) in enumerate(segs):
        ab = b_ - a
        denom = float(ab @ ab) or 1e-9
        t = np.clip(((co - a) @ ab) / denom, 0.0, 1.0)[:, None]
        d[:, j] = np.linalg.norm(co - (a + t * ab), axis=1)
    near = np.argsort(d, axis=1)[:, :k]
    groups = {n: o.vertex_groups.new(name=n) for n in names}
    for vi in range(len(co)):
        js = near[vi]
        w = 1.0 / (d[vi, js] + 1e-4)
        w = w / w.sum()
        for j, wj in zip(js, w):
            if wj > 0.02:
                groups[names[j]].add([vi], float(wj), "REPLACE")
    o.parent = armature
    o.matrix_parent_inverse = armature.matrix_world.inverted()
    mod = o.modifiers.new("Armature", "ARMATURE")
    mod.object = armature


used, cov = "AUTO", try_bind("ARMATURE_AUTO")
if cov < args.min_coverage:
    log(f"AUTO (bone heat) coverage {cov:.1%} < {args.min_coverage:.0%} -> trying ENVELOPE")
    used, cov = "ENVELOPE", try_bind("ARMATURE_ENVELOPE")
if cov < args.min_coverage:
    log(f"ENVELOPE coverage {cov:.1%} < {args.min_coverage:.0%} -> PROXIMITY (nearest deform bone)")
    proximity_weights(obj, rig, def_bones)
    used, cov = "PROXIMITY", coverage(obj)
log(f"weights={used} coverage={cov:.1%} ({time.time() - T0:.1f}s)")
if cov < 0.5:
    sys.exit("binding failed: less than half the vertices are weighted")

# ── 5. test animation on control bones ─────────────────────────────────────
scene = bpy.context.scene
scene.frame_start, scene.frame_end = 1, args.frames
scene.render.fps = args.fps
if not args.no_anim:
    select_only(rig)
    bpy.ops.object.mode_set(mode="POSE")
    pb = rig.pose.bones
    bob = size.z * 0.02
    stride = max(size.x, size.y) * 0.08
    lift = size.z * 0.05

    def first(*names):
        for n in names:
            if n in pb:
                return pb[n]
        return None

    torso = first("torso", "root")
    head = first("head")
    # human: hand_ik.*; quadruped (Basic Quadruped): front_foot_ik.*
    feet = [("foot_ik.L", 0.0), ("foot_ik.R", 0.5), ("hand_ik.L", 0.5), ("hand_ik.R", 0.0),
            ("front_foot_ik.L", 0.5), ("front_foot_ik.R", 0.0)]
    rest = {n: pb[n].matrix.copy() for n, _ in feet if n in pb}
    if torso:
        rest["torso"] = torso.matrix.copy()
    N = args.frames
    for f in range(1, N + 1):
        ph = (f - 1) / N  # 0..1 over the cycle
        scene.frame_set(f)
        if torso:
            torso.matrix = Matrix.Translation(Vector((0, 0, bob * math.sin(ph * 4 * math.pi)))) @ rest["torso"]
            torso.keyframe_insert("location", frame=f)
        for name, off in feet:
            if name not in rest:
                continue
            a = (ph + off) * 2 * math.pi
            dy = -stride * math.cos(a)                 # forward/back along -Y (facing direction)
            dz = max(0.0, math.sin(a)) * lift          # lift only on the swing half
            pb[name].matrix = Matrix.Translation(Vector((0, dy, dz))) @ rest[name]
            pb[name].keyframe_insert("location", frame=f)
            bpy.context.view_layer.update()
        if head:
            head.rotation_mode = "XYZ"
            head.rotation_euler = (math.radians(6) * math.sin(ph * 4 * math.pi), 0, 0)
            head.keyframe_insert("rotation_euler", frame=f)
    bpy.ops.object.mode_set(mode="OBJECT")
    act = rig.animation_data.action if rig.animation_data else None
    if act:
        act.name = "AutoCycle"
        try:  # Blender 5.x slotted actions: count curves via layers/strips/channelbags
            n = sum(len(cb.fcurves) for layer in act.layers for strip in layer.strips for cb in strip.channelbags)
        except AttributeError:
            n = -1
        log(f"animation 'AutoCycle' {N} frames @ {args.fps} fps, {n} fcurves, bones={[k for k in rest] + (['head'] if head else [])}")
    else:
        log("WARNING: no action created")

# ── 6. export ──────────────────────────────────────────────────────────────
os.makedirs(os.path.dirname(os.path.abspath(args.dst)), exist_ok=True)
if args.save_blend:
    bpy.ops.wm.save_as_mainfile(filepath=args.save_blend)
    log(f"saved {args.save_blend}")
select_only(obj, rig, active=rig)
bpy.ops.export_scene.gltf(
    filepath=args.dst,
    export_format="GLB",
    use_selection=True,
    export_skins=True,
    export_def_bones=True,
    export_animations=not args.no_anim,
    export_frame_range=True,
    export_anim_single_armature=True,
    export_force_sampling=True,
    export_materials="EXPORT",
    export_yup=True,
)
log(f"wrote {args.dst} ({os.path.getsize(args.dst) / 1e6:.1f} MB) in {time.time() - T0:.1f}s")
