"""Measure actual hog geometry before rigging: where are the legs, where is the head?

The rig has been placed by bounding-box fractions (legs at along 0.26/0.72), which is
guesswork. If the bones do not sit inside the real legs, no weighting scheme can work.
This prints what the mesh actually looks like so the rig can be built to fit it.
"""
import sys

import bpy
import numpy as np

path = sys.argv[-1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=path)

obj = max([o for o in bpy.data.objects if o.type == "MESH"],
          key=lambda o: len(o.data.vertices))
co = np.array([v.co[:] for v in obj.data.vertices], dtype=np.float64)
lo, hi = co.min(axis=0), co.max(axis=0)
size = hi - lo
print(f"[geo] verts={len(co)} size={np.round(size, 3)}")

# longest horizontal axis = travel axis
axis = 0 if size[0] >= size[1] else 1
other = 1 - axis
along = (co[:, axis] - lo[axis]) / size[axis]
across = (co[:, other] - lo[other]) / size[other]
up = (co[:, 2] - lo[2]) / size[2]
print(f"[geo] travel axis={'XYZ'[axis]}  length={size[axis]:.3f} width={size[other]:.3f} height={size[2]:.3f}")

# Cross-section profile along the body: mean |lateral spread| and vertical extent.
print("[geo] along-band profile (n, lateral width, min_z, max_z)")
for i in range(10):
    a0, a1 = i / 10, (i + 1) / 10
    sel = (along >= a0) & (along < a1)
    if not sel.any():
        continue
    w = co[sel][:, other]
    print(f"   {a0:.1f}-{a1:.1f}: n={sel.sum():6d} width={w.max()-w.min():.3f} "
          f"z=[{co[sel][:, 2].min():.3f},{co[sel][:, 2].max():.3f}]")

# Legs: cluster the lowest slab in the horizontal plane.
for slab in ((0.05, 0.20), (0.15, 0.30)):
    sel = (up >= slab[0]) & (up <= slab[1])
    pts = co[sel]
    print(f"[geo] leg slab up={slab}: n={len(pts)}")
    if len(pts) < 100:
        continue
    # simple 4-quadrant split around the median, then report each cluster centroid
    a_mid = np.median(pts[:, axis])
    c_mid = np.median(pts[:, other])
    for la, side_a in (("rear", pts[:, axis] < a_mid), ("front", pts[:, axis] >= a_mid)):
        for lc, side_c in (("left", pts[:, other] < c_mid), ("right", pts[:, other] >= c_mid)):
            q = pts[side_a & side_c]
            if len(q) < 50:
                continue
            cen = q.mean(axis=0)
            r = np.sqrt(((q[:, [axis, other]] - cen[[axis, other]]) ** 2).sum(axis=1))
            print(f"     {la}-{lc}: n={len(q):5d} centre_along={(cen[axis]-lo[axis])/size[axis]:.3f} "
                  f"centre_across={(cen[other]-lo[other])/size[other]:.3f} "
                  f"z_mean={cen[2]:.3f} radius={r.mean():.3f} max_r={r.max():.3f}")
