"""Audit skin weights by height band.

Displacement spread is a muddy metric: a spine rotation legitimately moves the
upper body non-uniformly. The precise question is whether LEG bones still hold
weight above the hips — that is what tears the snout and back.
"""
import sys

import bpy

path = sys.argv[-1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=path)

obj = max([o for o in bpy.data.objects if o.type == "MESH"],
          key=lambda o: len(o.data.vertices))
me = obj.data

leg_groups = {vg.index for vg in obj.vertex_groups
              if "_upper" in vg.name or "_lower" in vg.name}
print(f"[audit] mesh {obj.name} verts={len(me.vertices)} legs={len(leg_groups)}")

zs = [v.co.z for v in me.vertices]
z0, z1 = min(zs), max(zs)
span = max(z1 - z0, 1e-9)

bands = {}
for v in me.vertices:
    h = (v.co.z - z0) / span
    w = sum(g.weight for g in v.groups if g.group in leg_groups)
    key = round(h, 1)
    bands.setdefault(key, []).append(w)

print("[audit] height band -> mean leg weight, max leg weight, count")
for key in sorted(bands):
    ws = bands[key]
    print(f"   {key:.1f}-{key+0.1:.1f}: mean={sum(ws)/len(ws):.3f} "
          f"max={max(ws):.3f} n={len(ws)}")

above = [w for k, ws in bands.items() if k >= 0.7 for w in ws]
if above:
    print(f"[audit] ABOVE 70% height: max leg weight = {max(above):.4f} "
          f"({'CLEAN' if max(above) < 0.01 else 'LEAKING'})")

# Longitudinal audit: the face is the forward end of the body, and it sits low
# enough that a height-only test passes while the snout still rides the front legs.
xs = [v.co.x for v in me.vertices]
ys = [v.co.y for v in me.vertices]
if (max(xs) - min(xs)) >= (max(ys) - min(ys)):
    axis, lo_, hi_ = 0, min(xs), max(xs)
else:
    axis, lo_, hi_ = 1, min(ys), max(ys)
span_l = max(hi_ - lo_, 1e-9)

front = []
rear = []
for v in me.vertices:
    along = (v.co[axis] - lo_) / span_l
    w = sum(g.weight for g in v.groups if g.group in leg_groups)
    if along >= 0.85:
        front.append(w)
    elif along <= 0.15:
        rear.append(w)
# NOTE: both ends of the animal have legs, so a leg weight of 1.0 at one end is
# normal. Use these numbers to compare ends against each other, not as a pass/fail.
for label, vals in ((f"end A (along>=0.85)", front), (f"end B (along<=0.15)", rear)):
    if vals:
        print(f"[audit] {label}: n={len(vals)} max leg weight = {max(vals):.4f}")
