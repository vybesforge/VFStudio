"""Build a rig from hand-picked joints.

Why this exists: automatic rigging guessed bone positions from bounding-box
fractions, and the measurements proved the guess wrong on this asset (legs sat at
along 0.42/0.83, not 0.26/0.72, and the left and right legs are not symmetric).
Hand-picked joints remove the guess entirely.

Joints arrive in the GLB's own glTF space (Y-up). Blender imports glTF as Z-up with
(x, y, z)_gltf -> (x, -z, y)_blender, so every joint is converted the same way.

Usage:
  blender -b --python rig_from_joints.py -- <src.glb> <dst.glb> <joints.json> [--scale-to 2.0]
"""
import json
import math
import sys

import bpy
import numpy as np
from mathutils import Quaternion, Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
SRC, DST, JOINTS_JSON = argv[0], argv[1], argv[2]
TARGET_LEN = 2.0
if "--scale-to" in argv:
    TARGET_LEN = float(argv[argv.index("--scale-to") + 1])

FRAMES = 24

# ── load ────────────────────────────────────────────────────────────────
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SRC)

meshes = [o for o in bpy.data.objects if o.type == "MESH"]
if not meshes:
    sys.exit("no mesh in GLB")
obj = max(meshes, key=lambda o: len(o.data.vertices))
for stray in [o for o in meshes if o is not obj]:
    bpy.data.objects.remove(stray, do_unlink=True)

# ── scale to a real-world length ────────────────────────────────────────
bb = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
size = Vector((max(v.x for v in bb) - min(v.x for v in bb),
               max(v.y for v in bb) - min(v.y for v in bb),
               max(v.z for v in bb) - min(v.z for v in bb)))
horiz = max(size.x, size.y)
factor = TARGET_LEN / horiz if horiz > 1e-6 else 1.0
if abs(factor - 1.0) > 1e-6:
    obj.scale = [s * factor for s in obj.scale]
    bpy.context.view_layer.update()
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
print(f"[rig] scaled x{factor:.3f} to length {TARGET_LEN:.2f} m")

# ── joints: glTF Y-up -> Blender Z-up ───────────────────────────────────
raw = json.loads(open(JOINTS_JSON).read())
J = {}
for name, p in raw.items():
    # The picker saves bookkeeping alongside the joints (_template, _source, _src); those
    # are strings, and indexing one as a point is what crashed the build on 2026-11-02.
    if name.startswith("_") or not isinstance(p, dict) or not {"x", "y", "z"} <= set(p):
        continue
    J[name] = Vector((p["x"], -p["z"], p["y"])) * factor
print(f"[rig] {len(J)} joints: {', '.join(sorted(J))}")

REQUIRED = ["neck", "head", "spine", "hips"]
LEG_TAGS = ["FL", "FR", "BL", "BR"]
missing = [n for n in REQUIRED if n not in J] + \
          [f"{t}_{p}" for t in LEG_TAGS for p in ("hip", "knee", "hoof") if f"{t}_{p}" not in J]
if missing:
    sys.exit(f"missing joints: {missing}")

co = np.array([v.co[:] for v in obj.data.vertices], dtype=np.float64)
z_lo, z_hi = co[:, 2].min(), co[:, 2].max()

# ── armature ────────────────────────────────────────────────────────────
arm_data = bpy.data.armatures.new("rig")
arm = bpy.data.objects.new("rig", arm_data)
bpy.context.scene.collection.objects.link(arm)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="EDIT")
eb = arm_data.edit_bones

root = eb.new("root")
root.head = J["hips"]
root.tail = J["spine"]

spine = eb.new("spine")
spine.head = J["spine"]
spine.tail = J["neck"]
spine.parent = root
spine.use_connect = True

neck = eb.new("neck")
neck.head = J["neck"]
neck.tail = J["head"]
neck.parent = spine
neck.use_connect = True

head = eb.new("head")
head.head = J["head"]
head.tail = J["head"] + (J["head"] - J["neck"]) * 0.35
head.parent = neck
head.use_connect = True

legs = {}
for tag in LEG_TAGS:
    hip, knee, hoof = J[f"{tag}_hip"], J[f"{tag}_knee"], J[f"{tag}_hoof"]
    upper = eb.new(f"{tag}_upper")
    upper.head, upper.tail = hip, knee
    upper.parent = spine if tag.startswith("F") else root
    lower = eb.new(f"{tag}_lower")
    lower.head, lower.tail = knee, hoof
    lower.parent = upper
    lower.use_connect = True
    legs[tag] = (upper.name, lower.name)

bpy.ops.object.mode_set(mode="OBJECT")

# ── weights: nearest bone, but legs gated by real size and hip elevation ─
bones = [b.name for b in arm_data.bones if b.name != "root"]
segs = {n: (np.array(arm_data.bones[n].head_local[:]),
            np.array(arm_data.bones[n].tail_local[:])) for n in bones}

d = np.empty((len(co), len(bones)))
for j, n in enumerate(bones):
    a, b = segs[n]
    ab = b - a
    t = np.clip(((co - a) @ ab) / (float(ab @ ab) or 1e-9), 0.0, 1.0)[:, None]
    d[:, j] = np.linalg.norm(co - (a + t * ab), axis=1)

leg_bones = [j for j, n in enumerate(bones) if "_upper" in n or "_lower" in n]
# Leg thickness measured from the picked hoof/knee spacing, not invented.
thickness = np.mean([(J[f"{t}_hip"] - J[f"{t}_hoof"]).length for t in LEG_TAGS])
radius = max(thickness * 0.34, 0.03)
print(f"[rig] leg chain length {thickness:.3f} m -> weight radius {radius:.3f} m")

# Under each hip joint nothing but that leg may claim a vertex.
hip_z = {j: segs[bones[j]][0][2] for j in leg_bones}
for j in leg_bones:
    allowed = (co[:, 2] <= hip_z[j] + 0.02) & (d[:, j] <= radius)
    d[:, j] = np.where(allowed, d[:, j], np.inf)

order = np.argsort(d, axis=1)

# ── parametric weighting ───────────────────────────────────────────────
# Nearest-bone binding smeared: belly vertices fall inside a leg's capture zone and
# get dragged by it, and the only vertices that tear are isolated ones that disagree
# with their neighbours. Instead, give each leg a smooth cylinder fitted to the real
# limb, and let everything else belong to the body via a smooth falloff. Weights
# become continuous functions of position, so nothing can tear.
body_bones = [n for n in bones if not ("_upper" in n or "_lower" in n)]
body_idx = {n: bones.index(n) for n in body_bones}

W = np.zeros((len(co), len(bones)), dtype=np.float64)

# Normalised position along the body. The head gate must sit FORWARD of the front
# legs, not at the neck: the front-left leg is at along 0.869 while the neck is at
# ~0.84, so a neck-based gate locked the front leg out of leg binding entirely
# (FL_upper collapsed to 273 verts) while leaving the jaw exposed.
#
# NOTE: `size` was measured BEFORE the scale-to transform was applied, so these
# "normalised" values run 0..factor (e.g. 1.759 out of 2.001) rather than 0..1. That
# is harmless here because every position compared with them is in the same units,
# so the ratios still hold — but do NOT mix these with a true 0..1 fraction.
_len_axis = 0 if size[0] >= size[1] else 1
_lo_l = co[:, _len_axis].min()
_span_l = max(size[_len_axis], 1e-9)
along_norm = (co[:, _len_axis] - _lo_l) / _span_l
_front_along = max((J[f"{t}_hip"][_len_axis] - _lo_l) / _span_l for t in ("FL", "FR"))
head_along = _front_along + 0.03
print(f"[rig] front legs at along {_front_along:.3f} — head gate at {head_along:.3f}")

# Body: soft nearest-body-bone blend (sqrt falloff keeps it smooth but tight).
sigma = max(0.10 * np.mean(size[:2]), 1e-6)
body_d = d[:, [bones.index(n) for n in body_bones]]
body_w = np.exp(-((body_d / sigma) ** 2))
body_w /= np.maximum(body_w.sum(axis=1, keepdims=True), 1e-9)
for k, n in enumerate(body_bones):
    W[:, bones.index(n)] += body_w[:, k]

# Legs: cylinder capture with a smooth ramp, radius fitted per leg from the mesh.
for tag in LEG_TAGS:
    hip, knee, hoof = J[f"{tag}_hip"], J[f"{tag}_knee"], J[f"{tag}_hoof"]
    axis_pts = np.array([hip[:], knee[:], hoof[:]])
    seg = axis_pts[1] - axis_pts[0]
    seg2 = axis_pts[2] - axis_pts[1]

    def radial(p):
        best_r = np.full(len(p), np.inf)
        best_t = np.zeros(len(p))
        for a, ab in ((axis_pts[0], seg), (axis_pts[1], seg2)):
            t = np.clip(((p - a) @ ab) / (float(ab @ ab) or 1e-9), 0.0, 1.0)
            r = np.linalg.norm(p - (a + t[:, None] * ab), axis=1)
            closer = r < best_r
            best_r = np.where(closer, r, best_r)
            best_t = np.where(closer, t, best_t)
        return best_r, best_t

    # fit the limb radius from vertices near the lower half of this leg only
    near = (co[:, 2] <= knee[2] + 0.02) & (co[:, 2] >= hoof[2] - 0.02)
    r_near, _ = radial(co)  # cheap enough at this size
    probe = r_near[near]
    probe = probe[probe < 0.6]
    R = float(np.percentile(probe, 60)) if probe.size else 0.08
    # Cap below a real limb's radius: a fat cylinder re-captures the belly, which is
    # the smearing this parametric scheme exists to prevent.
    R = max(min(R, 0.12), 0.02)
    r_in, r_out = R * 0.85, R * 1.35

    r, _t = radial(co)
    ramp = np.clip((r_out - r) / max(r_out - r_in, 1e-6), 0.0, 1.0)
    ramp = ramp * ramp * (3 - 2 * ramp)            # smoothstep
    # fade out above the hip joint so the leg never claims the torso
    fade = np.clip((hip[2] + 0.03 - co[:, 2]) / 0.10, 0.0, 1.0)
    leg_weight = ramp * fade
    # Nothing forward of the front legs may be claimed by a leg — that region is the
    # snout and jaw, which hang low enough to sit inside the front legs' capture
    # radius and made the mouth swing with the walk.
    leg_weight = np.where(along_norm > head_along, 0.0, leg_weight)

    upper_j, lower_j = bones.index(f"{tag}_upper"), bones.index(f"{tag}_lower")
    below_knee = co[:, 2] <= knee[2]
    W[:, upper_j] += leg_weight * np.where(below_knee, 0.35, 1.0)
    W[:, lower_j] += leg_weight * np.where(below_knee, 1.0, 0.0)
    print(f"[rig] {tag}: fitted limb radius {R:.3f} m")

# Body yields to leg weight, so the two never fight over a vertex.
leg_cols = [bones.index(n) for n in bones if "_upper" in n or "_lower" in n]
leg_total = np.clip(W[:, leg_cols].sum(axis=1), 0.0, 1.0)   # 1-D: keep it broadcastable
for n in body_bones:
    W[:, bones.index(n)] *= (1.0 - leg_total)
W /= np.maximum(W.sum(axis=1, keepdims=True), 1e-9)
print(f"[rig] parametric weights built (leg capture + smooth body)")

# Guarantee every bone owns some geometry. An empty bone means that limb cannot
# deform at all (a hoof that stays behind while the leg swings is exactly how that
# shows up), so capture the nearest vertices for any empty bone.
# NOTE: this must run AFTER island binding, otherwise a later island pass can leave a
# bone with nothing.

me = obj.data
edges = np.empty(len(me.edges) * 2, dtype=np.int64)
me.edges.foreach_get("vertices", edges)
e0, e1 = edges[0::2], edges[1::2]

# ── island-rigid skinning ──────────────────────────────────────────────
# This mesh is a soup of ~1,585 separate islands (normal for TRELLIS output). Any
# per-vertex weighting tears wherever one island spans two bones, which is exactly
# the smearing. Binding each island wholesale to a single bone makes intra-island
# stretching impossible by construction.
parent = np.arange(len(co))


def find(a):
    while parent[a] != a:
        parent[a] = parent[parent[a]]
        a = parent[a]
    return a


for u, v in zip(e0, e1):
    ru, rv = find(u), find(v)
    if ru != rv:
        parent[rv] = ru
labels = np.array([find(i) for i in range(len(co))])
uniq = {lab: k for k, lab in enumerate(np.unique(labels))}
island = np.array([uniq[lab] for lab in labels])
n_islands = len(uniq)
print(f"[rig] {n_islands} islands — binding each rigidly to its dominant bone")

# Dominant bone per island, weighted by how strongly the island belongs.
scores = np.zeros((n_islands, len(bones)))
np.add.at(scores, island, W)

# Any island forward of the neck is head geometry: forbid leg bones outright so the
# jaw/face can never bind to a front leg, regardless of raw distance.
island_along = np.zeros(n_islands)
np.add.at(island_along, island, along_norm)
island_size = np.maximum(np.bincount(island), 1)
island_along /= island_size
head_islands = island_along > head_along
if head_islands.any():
    leg_cols = [bones.index(n) for n in bones if "_upper" in n or "_lower" in n]
    scores[np.ix_(np.nonzero(head_islands)[0], leg_cols)] = 0.0
    print(f"[rig] {int(head_islands.sum())} head islands locked to body bones")

dominant = scores.argmax(axis=1)

W_island = np.zeros_like(W)
W_island[np.arange(len(co)), dominant[island]] = 1.0
W = W_island

sizes = np.bincount(island)
print(f"[rig] largest island {sizes.max()} verts, median {int(np.median(sizes))}")

# Now guarantee every bone owns geometry, by handing it the nearest whole island.
isl_centroid = np.zeros((n_islands, 3))
np.add.at(isl_centroid, island, co)
isl_centroid /= np.maximum(np.bincount(island), 1)[:, None]

for j, n in enumerate(bones):
    if W[:, j].sum() > 1e-6:
        continue
    a, b = segs[n]
    ab = b - a
    t = np.clip(((isl_centroid - a) @ ab) / (float(ab @ ab) or 1e-9), 0.0, 1.0)
    dist = np.linalg.norm(isl_centroid - (a + t[:, None] * ab), axis=1)
    pick = int(dist.argmin())
    W[island == pick] = 0.0
    W[island == pick, j] = 1.0
    print(f"[rig] {n} had no islands — assigned nearest island ({sizes[pick]} verts)")
e0, e1 = edges[0::2], edges[1::2]
deg = (np.bincount(e0, minlength=len(co)) + np.bincount(e1, minlength=len(co)))
deg = np.maximum(deg, 1)

for _ in range(4):
    smoothed = np.empty_like(W)
    for b in range(len(bones)):
        acc = (np.bincount(e0, weights=W[e1, b], minlength=len(co)) +
               np.bincount(e1, weights=W[e0, b], minlength=len(co)))
        smoothed[:, b] = 0.5 * W[:, b] + 0.5 * (acc / deg)
    W = smoothed
    W /= np.maximum(W.sum(axis=1, keepdims=True), 1e-9)

# Keep the four strongest influences (glTF stores at most four) and renormalise.
if len(bones) > 4:
    cut = np.partition(W, -4, axis=1)[:, -4][:, None]
    W = np.where(W >= cut, W, 0.0)
W /= np.maximum(W.sum(axis=1, keepdims=True), 1e-9)
print(f"[rig] weights smoothed over {len(me.edges)} edges, 4 iterations")

for vg in list(obj.vertex_groups):
    obj.vertex_groups.remove(vg)
groups = {n: obj.vertex_groups.new(name=n) for n in bones}


def assign(group, idx, wts):
    if len(idx) == 0:
        return
    q = np.rint(wts * 100).astype(np.int32)
    o = np.argsort(q)
    qs, ids = q[o], idx[o]
    bounds = np.flatnonzero(np.diff(qs)) + 1
    for chunk, cidx in zip(np.split(qs, bounds), np.split(ids, bounds)):
        if len(chunk):
            group.add(cidx.tolist(), float(chunk[0]) / 100.0, "REPLACE")


for j, n in enumerate(bones):
    sel = np.nonzero(W[:, j] > 0.01)[0]
    assign(groups[n], sel, W[sel, j])

mod = obj.modifiers.new("Armature", "ARMATURE")
mod.object = arm
obj.parent = arm

counts = {n: 0 for n in bones}
idx_of = {vg.name: vg.index for vg in obj.vertex_groups}
for v in obj.data.vertices:
    for g in v.groups:
        for n, i in idx_of.items():
            if g.group == i and g.weight > 1e-4:
                counts[n] += 1
print("[rig] weighted verts per bone: " +
      ", ".join(f"{n}={c}" for n, c in sorted(counts.items())))
empty = [n for n, c in counts.items() if c == 0]
if empty:
    print(f"[rig] WARNING bones with no vertices: {empty}")

# ── trot ────────────────────────────────────────────────────────────────
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="POSE")

swing = math.radians(22)
quarter = FRAMES // 4

# Travel axis is the longer horizontal one; swing about the other.
axis = 0 if (co[:, 0].max() - co[:, 0].min()) >= (co[:, 1].max() - co[:, 1].min()) else 1
swing_world = Vector((0.0, 0.0, 0.0))
swing_world[1 - axis] = 1.0

phase = {"FL": 0.0, "BR": 0.0, "FR": 0.5, "BL": 0.5}
for tag, (upper_name, lower_name) in legs.items():
    off = int(phase[tag] * FRAMES)
    for bone_name, amp in ((upper_name, swing), (lower_name, swing * 0.6)):
        pb = arm.pose.bones[bone_name]
        pb.rotation_mode = "QUATERNION"
        local_axis = (pb.bone.matrix_local.to_3x3().inverted() @ swing_world).normalized()
        for step, f in enumerate((-1.0, 0.0, 1.0, 0.0)):
            frame = (off + step * quarter) % FRAMES + 1
            pb.rotation_quaternion = Quaternion(local_axis, amp * f)
            pb.keyframe_insert("rotation_quaternion", frame=frame)

# gentle body bob on the root
pb = arm.pose.bones["root"]
pb.rotation_mode = "QUATERNION"
for frame, ang in ((1, 0.0), (FRAMES // 2 + 1, math.radians(2.5)), (FRAMES + 1, 0.0)):
    pb.rotation_quaternion = Quaternion(Vector((0, 1, 0)), ang)
    pb.keyframe_insert("rotation_quaternion", frame=frame)

bpy.ops.object.mode_set(mode="OBJECT")
bpy.context.scene.frame_start = 1
bpy.context.scene.frame_end = FRAMES

bpy.ops.object.select_all(action="DESELECT")
arm.select_set(True)
obj.select_set(True)
bpy.context.view_layer.objects.active = arm
bpy.ops.export_scene.gltf(
    filepath=DST, export_format="GLB", use_selection=True,
    export_animations=True, export_frame_range=True,
    export_anim_single_armature=True, export_skins=True,
)
print(f"[rig] wrote {DST}")
print("done:")
