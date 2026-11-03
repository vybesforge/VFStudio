"""animate_clip — key a named locomotion cycle onto an already-rigged GLB.

  bin/blender -b --python tools/anim/animate_clip.py -- <in.glb> <out.glb>
      [--clip walk|trot|gallop|idle] [--frames 24] [--fps 24] [--amp 22]

This is the step after the joint picker's "Build rig": the rig supplies bones and weights,
this supplies motion, and the exported GLB carries one named clip that the VR room's Anim
button, Godot, or any glTF player can loop.

No motion library is installed locally, so the clips are procedural: a sine swing per leg
bone (phased per gait), a knee/carpal counter-swing, a body bob and a head counter-rotation.
Bone-space conversion follows scratch/rig_from_joints.py — the swing axis is chosen in world
space from the mesh's long horizontal axis, then rotated into each bone's local frame, which
is the part that differs between a hand-built bone chain and a Rigify metarig.

Bones are found by name: FL/FR/BL/BR_upper|lower (quadruped, from rig_from_joints.py) and
thigh/shin/upper_arm/forearm/foot_ik/hand_ik with .L/.R (Rigify, from rigify_auto.py).
"""
import argparse
import math
import sys

import bpy
from mathutils import Quaternion, Vector

ARGV = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
ap = argparse.ArgumentParser()
ap.add_argument("src")
ap.add_argument("dst")
ap.add_argument("--clip", default="walk", choices=["walk", "trot", "gallop", "idle"])
ap.add_argument("--frames", type=int, default=24)
ap.add_argument("--fps", type=int, default=24)
ap.add_argument("--amp", type=float, default=22.0, help="leg swing in degrees")
a = ap.parse_args(ARGV)

FRAMES, FPS = a.frames, a.fps

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=a.src)

arms = [o for o in bpy.context.scene.objects if o.type == "ARMATURE"]
if not arms:
    sys.exit("[anim] no armature in the GLB — build the rig first (panel: Build rig)")
arm = max(arms, key=lambda o: len(o.data.bones))
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
print(f"[anim] armature {arm.name}: {len(arm.data.bones)} bones, {len(meshes)} mesh(es)")

# start from a clean action list so the export holds exactly one named clip
for act in list(bpy.data.actions):
    bpy.data.actions.remove(act)
if arm.animation_data:
    arm.animation_data_clear()

bones = {b.name for b in arm.data.bones}

# ── limbs: tag -> [(bone, amplitude scale)] ──────────────────────────────
# tag is F/B (front/back, or left/right for a biped) + side, which is what the gait tables key on.
SEG_SCALE = {"thigh": 1.0, "shin": 0.55, "foot": 0.25, "toe": 0.15,
             "upper_arm": 0.7, "forearm": 0.35, "hand": 0.15, "shoulder": 0.25}
legs = {}
for tag in ("FL", "FR", "BL", "BR"):           # hand-built chain from rig_from_joints.py
    chain = [(f"{tag}_upper", 1.0), (f"{tag}_lower", 0.55)]
    chain = [(n, s) for n, s in chain if n in bones]
    if chain:
        legs[tag] = chain
if not legs:
    # Rigify exports only DEF- bones: DEF-thigh.L / DEF-front_thigh.L (quadruped metarig) or
    # DEF-thigh.L / DEF-upper_arm.L (biped). The ".001" twins are secondary deform copies —
    # animating them alongside their parent would double the rotation.
    for b in sorted(bones):
        c = b[4:] if b.startswith("DEF-") else b
        if c.endswith(".001"):
            continue
        side = "L" if c.endswith(".L") else "R" if c.endswith(".R") else None
        if not side:
            continue
        base = c[:-2]
        seg = base.replace("front_", "")
        if seg not in SEG_SCALE:
            continue
        kind = "F" if base.startswith("front_") else ("B" if seg in ("thigh", "shin", "foot", "toe") else "L")
        legs.setdefault(f"{kind}{side}", []).append((b, SEG_SCALE[seg]))
if not legs:
    sys.exit("[anim] no leg/arm bones recognised — expected FL_upper…, thigh.L…, or similar")
print(f"[anim] limbs: {', '.join(f'{k}={len(v)}' for k, v in legs.items())}")

# ── gait: phase per limb tag (fraction of the cycle) ─────────────────────
GAITS = {
    # lateral-sequence walk: LH, LF, RH, RF (arms on a biped counter-swing: LL/LR)
    "walk": {"BL": 0.00, "FL": 0.25, "BR": 0.50, "FR": 0.75, "LL": 0.50, "LR": 0.00},
    # diagonal pairs move together
    "trot": {"FL": 0.00, "BR": 0.00, "FR": 0.50, "BL": 0.50, "LL": 0.50, "LR": 0.00},
    # 4-beat gallop: front pair, then back pair
    "gallop": {"FL": 0.00, "FR": 0.05, "BL": 0.40, "BR": 0.45, "LL": 0.55, "LR": 0.05},
    "idle": {k: 0.0 for k in ("FL", "FR", "BL", "BR", "LL", "LR")},
}
phase_of = GAITS[a.clip]
amp = math.radians(a.amp) * (1.5 if a.clip == "gallop" else 1.0)
if a.clip == "idle":
    amp = math.radians(1.5)                    # barely-there weight shift

# long horizontal axis = travel; swing about the other horizontal axis
co = []
for m in meshes:
    co += [m.matrix_world @ v.co for v in m.data.vertices[:20000]]
if not co:
    sys.exit("[anim] no mesh vertices to measure")
xs = [p.x for p in co]
ys = [p.y for p in co]
zs = [p.z for p in co]
axis = 0 if (max(xs) - min(xs)) >= (max(ys) - min(ys)) else 1
swing_world = Vector((0.0, 0.0, 0.0))
swing_world[1 - axis] = 1.0
print(f"[anim] clip={a.clip} travel axis={'X' if axis == 0 else 'Y'} frames={FRAMES} amp={a.amp}°")

bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="POSE")

def key_swing(pb, angle_fn, world_axis):
    pb.rotation_mode = "QUATERNION"
    local_axis = (pb.bone.matrix_local.to_3x3().inverted() @ world_axis).normalized()
    for f in range(1, FRAMES + 1):
        t = (f - 1) / FRAMES
        pb.rotation_quaternion = Quaternion(local_axis, angle_fn(t))
        pb.keyframe_insert("rotation_quaternion", frame=f)

for tag, chain in legs.items():
    ph = phase_of.get(tag, 0.0)
    for bone, scale in chain:
        pb = arm.pose.bones[bone]
        if a.clip == "idle":
            key_swing(pb, lambda t: amp * scale * math.sin(2 * math.pi * t + (math.pi if tag in ("R", "BR", "FR") else 0.0)),
                      swing_world)
        else:
            # upper swings at cycle rate, lower lags a quarter and doubles back (knee)
            lag = 0.0 if scale == 1.0 else -0.12
            key_swing(pb, lambda t, s=scale, l=lag: amp * s * math.sin(2 * math.pi * (t + ph + l)), swing_world)

# body bob / pitch at twice the stride rate, and a head counter-rotation
root = next((n for n in ("root", "torso", "spine") if n in bones), None)
if root:
    pb = arm.pose.bones[root]
    bob = math.radians(2.5) * (2.0 if a.clip == "gallop" else 1.0)
    pitch_axis = Vector((0.0, 1.0, 0.0)) if axis == 0 else Vector((1.0, 0.0, 0.0))
    key_swing(pb, lambda t: bob * math.sin(4 * math.pi * t), pitch_axis)
if "head" in bones:
    pb = arm.pose.bones["head"]
    key_swing(pb, lambda t: math.radians(3.0) * math.sin(2 * math.pi * t), Vector((0.0, 0.0, 1.0)))
if "neck" in bones:
    pb = arm.pose.bones["neck"]
    key_swing(pb, lambda t: math.radians(2.0) * math.sin(2 * math.pi * t + 0.6), Vector((0.0, 0.0, 1.0)))

bpy.ops.object.mode_set(mode="OBJECT")

act = arm.animation_data.action if arm.animation_data else None
if act is None:
    act = bpy.data.actions.new(a.clip.capitalize())
    arm.animation_data_create()
    arm.animation_data.action = act
act.name = a.clip.capitalize()
act.use_fake_user = True
bpy.context.scene.frame_start = 1
bpy.context.scene.frame_end = FRAMES
bpy.context.scene.render.fps = FPS
bpy.context.scene.render.fps_base = 1.0

bpy.ops.object.select_all(action="DESELECT")
arm.select_set(True)
for m in meshes:
    m.select_set(True)
bpy.context.view_layer.objects.active = arm

bpy.ops.export_scene.gltf(
    filepath=a.dst, export_format="GLB", use_selection=True,
    export_animations=True, export_frame_range=True,
    export_anim_single_armature=True, export_skins=True,
)
print(f"[anim] action '{act.name}' {FRAMES} frames @ {FPS} fps -> {a.dst}")
print("done:")
