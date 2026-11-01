"""Print the horizontal width profile of a GLB, top-down, as fractions of height.

blender -b --python profile.py -- in.glb
"""
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=argv[0])
ms = [o for o in bpy.context.scene.objects if o.type == "MESH"]
for o in ms:
    o.select_set(True)
bpy.context.view_layer.objects.active = ms[0]
if len(ms) > 1:
    bpy.ops.object.join()
obj = bpy.context.view_layer.objects.active

pts = [obj.matrix_world @ v.co for v in obj.data.vertices]
zs = [p.z for p in pts]
lo, hi = min(zs), max(zs)
H = hi - lo
n = 20
print(f"[profile] height {H:.3f}  z {lo:.3f}..{hi:.3f}")
for i in range(n):
    z_hi = hi - H * i / n
    z_lo = hi - H * (i + 1) / n
    sel = [p for p in pts if z_lo <= p.z <= z_hi]
    if len(sel) < 6:
        print(f"  top {100*i/n:3.0f}-{100*(i+1)/n:3.0f}%  (empty)")
        continue
    xs = [p.x for p in sel]
    print(f"  top {100*i/n:3.0f}-{100*(i+1)/n:3.0f}%  width {max(xs)-min(xs):.3f}  verts {len(sel)}")
