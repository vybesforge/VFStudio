"""Identify which rig build a GLB carries, by its weight profile.

The radial-gate build binds ~154k vertices primarily to legs; the earlier
head-bone-only build bound ~234k, and the original (no head bone) ~246k. Counting
leg-bound vertices is the only reliable way to tell two files of identical size
apart.
"""
import sys

import bpy

path = sys.argv[-1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=path)

obj = max([o for o in bpy.data.objects if o.type == "MESH"],
          key=lambda o: len(o.data.vertices))
leg = {vg.index for vg in obj.vertex_groups
       if "_upper" in vg.name or "_lower" in vg.name}
head = {vg.index for vg in obj.vertex_groups if vg.name == "head"}

n_leg_dom = n_head = 0
for v in obj.data.vertices:
    lw = sum(g.weight for g in v.groups if g.group in leg)
    hw = sum(g.weight for g in v.groups if g.group in head)
    if lw > 0.5:
        n_leg_dom += 1
    if hw > 0.1:
        n_head += 1

print(f"[id] bones={sorted(vg.name for vg in obj.vertex_groups)}")
print(f"[id] leg-dominant verts (weight>0.5) = {n_leg_dom}")
print(f"[id] head-weighted verts (weight>0.1) = {n_head}")
print("[id] radial-gate build" if n_leg_dom < 180000 else "[id] PRE-radial build")
