"""Seed joints.json from measured geometry, in glTF coordinates.

Purpose: prove the picker -> API -> rig_from_joints chain works, and give a usable
starting rig that the user can then nudge in the browser rather than placing all
16 joints from scratch.

Writes glTF-space points (Y-up) because that is what the browser viewer reports:
Blender (x, y, z) -> glTF (x, z, -y).
"""
import json
import sys
from pathlib import Path

import bpy
import numpy as np

SRC = sys.argv[sys.argv.index("--") + 1]
OUT = Path("/Users/dcruse/media-stack/rig/joints.json")

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SRC)
obj = max([o for o in bpy.data.objects if o.type == "MESH"],
          key=lambda o: len(o.data.vertices))

co = np.array([v.co[:] for v in obj.data.vertices], dtype=np.float64)
lo, hi = co.min(axis=0), co.max(axis=0)
size = hi - lo
L_axis = 0 if size[0] >= size[1] else 1
W_axis = 1 - L_axis
H = size[2]

along = (co[:, L_axis] - lo[L_axis]) / size[L_axis]
across = (co[:, W_axis] - lo[W_axis]) / size[W_axis]
up = (co[:, 2] - lo[2]) / size[2]

slab = (up >= 0.05) & (up <= 0.30)
pts = co[slab]
a_mid = np.median(pts[:, L_axis])
c_mid = np.median(pts[:, W_axis])

legs = {}
for tag, front, left in (("BL", False, True), ("BR", False, False),
                         ("FL", True, True), ("FR", True, False)):
    sel = ((pts[:, L_axis] >= a_mid) == front) & ((pts[:, W_axis] < c_mid) == left)
    q = pts[sel]
    if len(q) < 50:
        continue
    c = q.mean(axis=0)
    legs[tag] = ((c[L_axis] - lo[L_axis]) / size[L_axis],
                 (c[W_axis] - lo[W_axis]) / size[W_axis])

def P(al, ac, u):
    v = np.zeros(3)
    v[L_axis] = lo[L_axis] + al * size[L_axis]
    v[W_axis] = lo[W_axis] + ac * size[W_axis]
    v[2] = lo[2] + u * H
    return v

joints_blender = {
    "hips": P(0.22, 0.50, 0.62),
    "spine": P(0.55, 0.50, 0.64),
    "neck": P(0.86, 0.50, 0.66),
    "head": P(1.00, 0.50, 0.52),
}
for tag, (al, ac) in legs.items():
    joints_blender[f"{tag}_hip"] = P(al, ac, 0.55)
    joints_blender[f"{tag}_knee"] = P(al, ac, 0.28)
    joints_blender[f"{tag}_hoof"] = P(al, ac, 0.03)

# Blender Z-up -> glTF Y-up
out = {}
for name, v in joints_blender.items():
    out[name] = {"x": round(float(v[0]), 4),
                 "y": round(float(v[2]), 4),
                 "z": round(float(-v[1]), 4)}

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(out, indent=1))
print(f"[seed] wrote {len(out)} joints -> {OUT}")
for k in sorted(out):
    print(f"   {k}: {out[k]}")
