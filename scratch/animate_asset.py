"""Rig a quadruped GLB and bake a looping trot cycle into glTF skeletal animation.

Deliberately anatomy-agnostic: leg positions are derived from the mesh bounding
box rather than hardcoded, because image-to-3D output has no fixed orientation
and Hunyuan/TRELLIS return different scales and axes.

blender -b --python animate_asset.py -- in.glb out.glb [--frames 24]
"""

import math
import sys

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
SRC, DST = argv[0], argv[1]
FRAMES = 24
if "--frames" in argv:
    FRAMES = int(argv[argv.index("--frames") + 1])

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.fps = FRAMES // 1 if FRAMES >= 1 else 24

bpy.ops.import_scene.gltf(filepath=SRC)
meshes = [o for o in scene.objects if o.type == "MESH"]
if not meshes:
    sys.exit("no mesh in GLB")

obj = meshes[0]
if len(meshes) > 1:
    bpy.context.view_layer.objects.active = obj
    for o in meshes:
        o.select_set(True)
    bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active

bb = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
xs = [v.x for v in bb]; ys = [v.y for v in bb]; zs = [v.z for v in bb]
lo = Vector((min(xs), min(ys), min(zs)))
hi = Vector((max(xs), max(ys), max(zs)))
size = hi - lo

# Reconstruction models hand back arbitrary units (TRELLIS normalises to ~1 m),
# which is wrong for a VR room where 1 unit = 1 metre. Normalise the longest
# horizontal dimension to a real-world length when --scale-to is given.
if "--scale-to" in sys.argv:
    target = float(sys.argv[sys.argv.index("--scale-to") + 1])
    horiz = max(size.x, size.y)
    if horiz > 1e-6:
        factor = target / horiz
        obj.scale = [s * factor for s in obj.scale]
        bpy.context.view_layer.update()
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        print(f"[anim] scaled x{factor:.3f} -> length {target:.2f} m")
        bb = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
        xs = [v.x for v in bb]; ys = [v.y for v in bb]; zs = [v.z for v in bb]
        lo = Vector((min(xs), min(ys), min(zs)))
        hi = Vector((max(xs), max(ys), max(zs)))
        size = hi - lo

ctr = (hi + lo) / 2

# The source GLB is Y-up, but Blender's glTF importer converts to Z-up. Inside
# this script the vertical axis is Z, and the two horizontal axes are X and Y.
# Travel axis = the longer horizontal dimension.
length_axis = 0 if size.x >= size.y else 1
width_axis = 1 if length_axis == 0 else 0
L = size[length_axis]
W = size[width_axis]
H = size.z
print(f"[anim] bbox {tuple(round(v,3) for v in size)} L={L:.3f} W={W:.3f} H={H:.3f}")

def P(along, up, across):
    """Point in world space from (along, up, across) fractions of the bbox."""
    v = Vector((ctr.x, ctr.y, lo.z))
    v[length_axis] = lo[length_axis] + along * L
    v[width_axis] = lo[width_axis] + across * W
    v.z = lo.z + up * H
    return v

# ── armature ────────────────────────────────────────────────────────────
arm_data = bpy.data.armatures.new("rig")
arm = bpy.data.objects.new("rig", arm_data)
scene.collection.objects.link(arm)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="EDIT")

eb = arm_data.edit_bones

# ── measure the actual legs instead of assuming bbox quadrants ──────────
# The previous rig put the legs at along 0.26 / 0.72, but the mesh has them at
# ~0.42 / ~0.83, and the real leg radius is 0.03-0.08 — so the bones sat outside
# the legs and the weighting radius swept up the belly and the mouth.
import numpy as np

_co = np.array([v.co[:] for v in obj.data.vertices], dtype=np.float64)
_lo, _hi = _co.min(axis=0), _co.max(axis=0)
_size = _hi - _lo
_along = (_co[:, length_axis] - _lo[length_axis]) / max(_size[length_axis], 1e-9)
_across = (_co[:, width_axis] - _lo[width_axis]) / max(_size[width_axis], 1e-9)
_up = (_co[:, 2] - _lo[2]) / max(_size[2], 1e-9)

_slab = (_up >= 0.05) & (_up <= 0.30)
_pts = _co[_slab]
_a_mid = np.median(_pts[:, length_axis])
_c_mid = np.median(_pts[:, width_axis])

measured = {}
for tag, front, left in (("BL", False, True), ("BR", False, False),
                         ("FL", True, True), ("FR", True, False)):
    sel = ((_pts[:, length_axis] >= _a_mid) == front) & \
          ((_pts[:, width_axis] < _c_mid) == left)
    q = _pts[sel]
    if len(q) < 50:
        continue
    cen = q.mean(axis=0)
    rad = np.sqrt(((q[:, [length_axis, width_axis]] -
                    cen[[length_axis, width_axis]]) ** 2).sum(axis=1))
    measured[tag] = {
        "along": (cen[length_axis] - _lo[length_axis]) / max(_size[length_axis], 1e-9),
        "across": (cen[width_axis] - _lo[width_axis]) / max(_size[width_axis], 1e-9),
        "radius": float(rad.mean()),
    }
    print(f"[anim] measured {tag}: along={measured[tag]['along']:.3f} "
          f"across={measured[tag]['across']:.3f} radius={measured[tag]['radius']:.3f}")

if not measured:
    sys.exit("could not measure legs")

front_along = np.mean([v["along"] for k, v in measured.items() if k.startswith("F")])
rear_along = np.mean([v["along"] for k, v in measured.items() if k.startswith("B")])
leg_radius = float(np.mean([v["radius"] for v in measured.values()]))
print(f"[anim] front={front_along:.3f} rear={rear_along:.3f} mean leg radius={leg_radius:.3f}")

root = eb.new("root")
root.head = P((rear_along + front_along) / 2, 0.60, 0.5)
root.tail = P(front_along, 0.62, 0.5)

spine = eb.new("spine")
spine.head = P(0.10, 0.58, 0.5)
spine.tail = P((rear_along + front_along) / 2, 0.60, 0.5)
spine.parent = root
spine.use_connect = True

# The face needs a bone of its own. Without one, every vertex forward of `root`
# had no nearby bone and bound to the FRONT LEGS instead — which is why half the
# snout rode the walk cycle.
head = eb.new("head")
head.head = P(front_along, 0.62, 0.5)
head.tail = P(1.00, 0.58, 0.5)
head.parent = root
head.use_connect = True

# four legs at their MEASURED positions
legs = {}
for name in ("FL", "FR", "BL", "BR"):
    m = measured[name]
    along, across = m["along"], m["across"]
    upper = eb.new(f"{name}_upper")
    upper.head = P(along, 0.52, across)
    upper.tail = P(along, 0.24, across)
    upper.parent = root if along > 0.5 else spine
    lower = eb.new(f"{name}_lower")
    lower.head = upper.tail
    lower.tail = P(along, 0.02, across)
    lower.parent = upper
    lower.use_connect = True
    legs[name] = (upper.name, lower.name)

bpy.ops.object.mode_set(mode="OBJECT")

# ── bind mesh ───────────────────────────────────────────────────────────
bpy.ops.object.select_all(action="DESELECT")
obj.select_set(True)
arm.select_set(True)
bpy.context.view_layer.objects.active = arm

bound = None
for mode in ("ARMATURE_AUTO", "ARMATURE_ENVELOPE", "ARMATURE_NAME"):
    try:
        bpy.ops.object.parent_set(type=mode)
        bound = mode
        break
    except Exception as exc:
        print(f"[anim] {mode} failed: {exc}")
if not bound:
    sys.exit("could not bind mesh to armature")

# Bone-heat weighting can silently fail for some bones ("failed to find a
# solution"), leaving them with no influence. Verify, and fall back to envelopes
# if any deforming bone ended up with an empty vertex group.
bone_names = [b.name for b in arm_data.bones if b.name != "root"]
vg_names = {vg.name for vg in obj.vertex_groups}
missing = [b for b in bone_names if b not in vg_names]
if missing:
    print(f"[anim] {len(missing)} bone(s) unweighted after {bound}: {missing[:4]} — retrying with envelopes")
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    for vg in list(obj.vertex_groups):
        obj.vertex_groups.remove(vg)
    bpy.ops.object.parent_set(type="ARMATURE_ENVELOPE")
    bound = "ARMATURE_ENVELOPE"
print(f"[anim] bound with {bound}")


def has_real_weights(object_, bones):
    """True only if every deforming bone actually influences some vertices.

    Checking just that the vertex-group *names* exist is not enough: bone heat can
    fail ("failed to find solution"), leaving groups present but empty, and the
    glTF exporter then reports "Mesh_0 has no skin" and ships a rigid mesh that
    never deforms, however many animation curves it carries.
    """
    idx_to_bone = {}
    for vg in object_.vertex_groups:
        if vg.name in bones:
            idx_to_bone[vg.index] = vg.name
    counts = {name: 0 for name in bones}
    for v in object_.data.vertices:
        for g in v.groups:
            name = idx_to_bone.get(g.group)
            if name and g.weight > 1e-5:
                counts[name] += 1
    empty = [n for n, c in counts.items() if c == 0]
    return (not empty), counts, empty


def proximity_weights(object_, armature, bones):
    """Bind by distance to each bone segment — deterministic, no solver.

    Bone heat needs a watertight, reasonably sized mesh; a 700k-tri reconstruction
    defeats it. Nearest-segment weighting always produces a usable skin, and for a
    four-legged trot the legs are far enough apart that it reads correctly.
    """
    import numpy as np
    from mathutils import Vector as V

    me = object_.data
    co = np.array([v.co[:] for v in me.vertices], dtype=np.float64)

    segs = {}
    for name in bones:
        b = armature.data.bones.get(name)
        if not b:
            continue
        segs[name] = (np.array(b.head_local[:]), np.array(b.tail_local[:]))

    names = list(segs)
    # point-to-segment distance for every vertex against every bone
    d = np.empty((len(co), len(names)), dtype=np.float64)
    for j, name in enumerate(names):
        a, b = segs[name]
        ab = b - a
        denom = float(ab @ ab) or 1e-9
        t = np.clip(((co - a) @ ab) / denom, 0.0, 1.0)[:, None]
        proj = a + t * ab
        d[:, j] = np.linalg.norm(co - proj, axis=1)

    # ── anatomical gating ───────────────────────────────────────────────
    # Plain nearest-bone weighting lets a leg bone claim the snout and the back,
    # because those vertices happen to be closer to a long leg segment than to the
    # short spine bone. Gate each leg to its own quadrant and below the hip line,
    # with a ramp so the transition blends instead of tearing.
    leg_idx = [j for j, n in enumerate(names) if "_upper" in n or "_lower" in n]
    if leg_idx:
        along = (co[:, length_axis] - lo[length_axis]) / max(L, 1e-9)
        across = (co[:, width_axis] - lo[width_axis]) / max(W, 1e-9)
        up = (co[:, 2] - lo.z) / max(H, 1e-9)
        hip_z = 0.52          # leg bones start at 52% of height
        band = 0.12           # ramp width around the hip
        ramp = np.clip((hip_z + band - up) / band, 0.0, 1.0)

        for j in leg_idx:
            name = names[j]
            # derive the leg's own quadrant from its bone head
            bh = segs[name][0]
            along_l = (bh[length_axis] - lo[length_axis]) / max(L, 1e-9)
            across_l = (bh[width_axis] - lo[width_axis]) / max(W, 1e-9)
            # Radial gate: a leg may only claim vertices within a real distance of
            # its own bone, scaled to the leg that was actually measured. The old
            # 0.16*L was 2-3x thicker than a real leg, so it swept up belly and mouth.
            radius = max(leg_radius * 1.8, 0.02)
            allowed = d[:, j] <= radius
            d[:, j] = np.where(allowed, d[:, j], np.inf)
        gated_ramp = ramp
    else:
        gated_ramp = None

    order = np.argsort(d, axis=1)
    nearest = order[:, 0]
    second = order[:, 1]
    dn = d[np.arange(len(co)), nearest]
    ds = d[np.arange(len(co)), second]

    # Blend between the two closest bones so joints bend instead of tearing.
    blend = np.clip(dn / np.maximum(ds, 1e-9), 0.0, 1.0)
    w_primary = 0.5 + 0.5 * blend
    w_secondary = 1.0 - w_primary

    # Damp leg influence above the hip and hand the remainder to the spine, so the
    # body stays rigid while the legs swing. This must cover BOTH the nearest and
    # second-nearest bone: a vertex whose nearest is the spine but whose second is a
    # leg otherwise keeps up to 0.5 leg weight high on the back/snout.
    spine_residual = np.zeros(len(co))
    if gated_ramp is not None and "spine" in names:
        is_leg = np.isin(nearest, leg_idx)
        lost = np.where(is_leg, w_primary * (1.0 - gated_ramp), 0.0)
        w_primary = w_primary - lost

        is_leg2 = np.isin(second, leg_idx)
        lost2 = np.where(is_leg2, w_secondary * (1.0 - gated_ramp), 0.0)
        w_secondary = w_secondary - lost2

        spine_residual = lost + lost2
        print(f"[anim] gated {int(is_leg.sum())} primary + {int(is_leg2.sum())} secondary "
              f"leg verts, mean damping {float(gated_ramp[is_leg | is_leg2].mean()) if (is_leg | is_leg2).any() else 0:.2f}")

    for vg in list(object_.vertex_groups):
        object_.vertex_groups.remove(vg)

    groups = {name: object_.vertex_groups.new(name=name) for name in names}

    def assign_bucketed(group, indices, weights):
        """Add vertices in weight buckets — one call per bucket, not per vertex."""
        if len(indices) == 0:
            return
        q = np.rint(weights * 100).astype(np.int32)
        order = np.argsort(q)
        q_sorted = q[order]
        idx_sorted = indices[order]
        bounds = np.flatnonzero(np.diff(q_sorted)) + 1
        for chunk, chunk_idx in zip(np.split(q_sorted, bounds), np.split(idx_sorted, bounds)):
            if len(chunk) == 0:
                continue
            group.add(chunk_idx.tolist(), float(chunk[0]) / 100.0, "REPLACE")

    nz_near = np.nonzero(np.ones(len(co), dtype=bool))[0]
    for j, name in enumerate(names):
        sel = np.nonzero(nearest == j)[0]
        assign_bucketed(groups[name], sel, w_primary[sel])
    for j, name in enumerate(names):
        sel = np.nonzero(second == j)[0]
        assign_bucketed(groups[name], sel, w_secondary[sel])

    # Residual leg weight transfers to the spine.
    if "spine" in names and spine_residual.any():
        nz = np.nonzero(spine_residual > 1e-4)[0]
        q = np.rint(spine_residual[nz] * 100).astype(np.int32)
        for bucket in np.unique(q):
            sel = nz[q == bucket]
            groups["spine"].add(sel.tolist(), float(bucket) / 100.0, "ADD")
    print(f"[anim] proximity weights applied across {len(names)} bones, {len(co)} verts")


ok, counts, empty = has_real_weights(obj, bone_names)
if not ok:
    print(f"[anim] {len(empty)} bone(s) have zero weighted verts: {empty[:5]}")
    proximity_weights(obj, arm, bone_names)
    ok, counts, empty = has_real_weights(obj, bone_names)

mod = next((m for m in obj.modifiers if m.type == "ARMATURE"), None)
if mod is None:
    mod = obj.modifiers.new("Armature", "ARMATURE")
    mod.object = arm
    print("[anim] added missing armature modifier")
else:
    mod.object = arm
print(f"[anim] weights ok={ok} min_verts={min(counts.values()) if counts else 0}")

# ── walk cycle (trot: diagonal pairs move together) ─────────────────────
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="POSE")

from mathutils import Quaternion, Vector

swing = math.radians(20)
lift = math.radians(14)
quarter = max(FRAMES // 4, 1)

# Legs must swing in the travel plane, i.e. rotate about the world axis that is
# horizontal AND perpendicular to the direction of travel. Rotating a bone on its
# local X instead swung the legs sideways, because bone roll is undefined unless
# set explicitly. Convert the world axis into each bone's local space.
swing_axis_world = Vector((0.0, 0.0, 0.0))
swing_axis_world[width_axis] = 1.0

phase = {"FL": 0, "BR": 0, "FR": 0.5, "BL": 0.5}  # diagonal pairs in antiphase

for name, (upper_name, lower_name) in legs.items():
    off = int(phase[name] * FRAMES)
    for bone_name, amplitude in ((upper_name, swing), (lower_name, lift)):
        pb = arm.pose.bones[bone_name]
        pb.rotation_mode = "QUATERNION"
        local_axis = (pb.bone.matrix_local.to_3x3().inverted() @ swing_axis_world).normalized()
        for step, factor in enumerate((-1.0, 0.0, 1.0, 0.0)):
            f = (off + step * quarter) % FRAMES + 1
            pb.rotation_quaternion = Quaternion(local_axis, amplitude * factor)
            pb.keyframe_insert("rotation_quaternion", frame=f)

# body bob
bpy.context.view_layer.objects.active = arm
pb_root = arm.pose.bones["root"]
pb_root.rotation_mode = "XYZ"
for step, bob in enumerate((0.0, 1.0, 0.0, 1.0)):
    f = step * quarter + 1
    pb_root.location = (0.0, bob * 0.012, 0.0)
    pb_root.keyframe_insert("location", frame=f)

bpy.ops.object.mode_set(mode="OBJECT")

action = arm.animation_data.action if arm.animation_data else None
if action:
    action.name = "Trot"
    # Blender 5.x slotted actions no longer expose .fcurves directly; count via
    # channelbags when available and skip interpolation tweaks if not.
    try:
        n_curves = sum(len(cb.fcurves) for layer in action.layers
                       for strip in layer.strips for cb in strip.channelbags)
        for layer in action.layers:
            for strip in layer.strips:
                for cb in strip.channelbags:
                    for fc in cb.fcurves:
                        for kp in fc.keyframe_points:
                            kp.interpolation = "BEZIER"
        print(f"[anim] action '{action.name}' with {n_curves} curves")
    except AttributeError:
        print(f"[anim] action '{action.name}' created (curve introspection unavailable)")

scene.frame_start = 1
scene.frame_end = FRAMES

# ── export with animation ───────────────────────────────────────────────
bpy.ops.object.select_all(action="DESELECT")
arm.select_set(True)
obj.select_set(True)
bpy.context.view_layer.objects.active = arm
bpy.ops.export_scene.gltf(
    filepath=DST,
    export_format="GLB",
    use_selection=True,
    export_animations=True,
    export_frame_range=True,
    export_anim_single_armature=True,
    export_skins=True,
    export_materials="EXPORT",
)
print(f"[anim] wrote {DST}")
