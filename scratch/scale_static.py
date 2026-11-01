"""Scale a GLB to a real-world length and re-export, statically.

The reconstruction hands back ~1 m units; the VR room treats 1 unit as 1 metre, so a
hog has to be ~2 m nose to tail. No rig, no animation — geometry and materials only.
"""
import sys

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
SRC, DST = argv[0], argv[1]
TARGET = float(argv[argv.index("--scale-to") + 1]) if "--scale-to" in argv else 2.0

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SRC)

meshes = [o for o in bpy.data.objects if o.type == "MESH"]
if not meshes:
    sys.exit("no mesh")
obj = max(meshes, key=lambda o: len(o.data.vertices))
for stray in [o for o in meshes if o is not obj]:
    bpy.data.objects.remove(stray, do_unlink=True)

bb = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
size = Vector((max(v.x for v in bb) - min(v.x for v in bb),
               max(v.y for v in bb) - min(v.y for v in bb),
               max(v.z for v in bb) - min(v.z for v in bb)))
horiz = max(size.x, size.y)
factor = TARGET / horiz if horiz > 1e-6 else 1.0
obj.scale = [s * factor for s in obj.scale]
bpy.context.view_layer.update()
bpy.ops.object.select_all(action="DESELECT")
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
print(f"[scale] x{factor:.3f} -> {TARGET:.2f} m")

bpy.ops.export_scene.gltf(filepath=DST, export_format="GLB", use_selection=True,
                          export_animations=False, export_skins=False)
print(f"[scale] wrote {DST}")
