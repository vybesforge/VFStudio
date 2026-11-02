"""verify_anim_glb.py — Blender 5.x headless: prove a GLB has a skin and a non-zero animation.

  ~/media-stack/bin/blender -b --python ~/media-stack/tools/anim/verify_anim_glb.py -- /abs/file.glb [--json /abs/out.json]

Imports the GLB, finds the mesh with an Armature modifier, evaluates it through the depsgraph at
frame_start, mid-cycle, and frame_end, and measures per-vertex displacement in world space.
Prints one JSON line:
  {"ok": true, "file": "...", "skinned": true, "bones": 32, "actions": ["AutoCycle"],
   "frames": [1, 24], "verts": 50234, "max_disp": 0.0412, "mean_disp": 0.0081,
   "moving_frac": 0.87, "tris": 100000}
ok = skinned AND at least one action AND max_disp > 1e-4. Exit code 1 otherwise.
"""
import json
import sys

import bpy
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if not argv:
    sys.exit("usage: ... -- file.glb [--json out.json]")
SRC = argv[0]
JSON_OUT = argv[argv.index("--json") + 1] if "--json" in argv else None

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SRC)
scene = bpy.context.scene

meshes = [o for o in bpy.data.objects if o.type == "MESH"]
skinned = [o for o in meshes if any(m.type == "ARMATURE" and m.object for m in o.modifiers)]
arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
actions = [a.name for a in bpy.data.actions]

# the GLB importer leaves the scene range at 1..250; use the action's own range instead
if bpy.data.actions:
    fr = bpy.data.actions[0].frame_range
    scene.frame_start, scene.frame_end = int(fr[0]), max(int(fr[0]) + 1, int(round(fr[1])))
res = {"ok": False, "file": SRC, "skinned": bool(skinned), "bones": sum(len(a.data.bones) for a in arms),
       "actions": actions, "frames": [scene.frame_start, scene.frame_end],
       "tris": sum(len(o.data.polygons) for o in meshes)}

if skinned and actions:
    obj = max(skinned, key=lambda o: len(o.data.vertices))
    dg = bpy.context.evaluated_depsgraph_get()

    def coords(frame):
        scene.frame_set(frame)
        dg.update()
        ev = obj.evaluated_get(dg)
        me = ev.to_mesh()
        n = len(me.vertices)
        arr = np.empty(n * 3)
        me.vertices.foreach_get("co", arr)
        arr = arr.reshape(n, 3) @ np.array(ev.matrix_world.to_3x3().transposed()) + np.array(ev.matrix_world.translation)
        ev.to_mesh_clear()
        return arr

    f0, f1 = scene.frame_start, scene.frame_end
    base = coords(f0)
    max_d = mean_d = moving = 0.0
    for f in {f0 + (f1 - f0) // 4, f0 + (f1 - f0) // 2, f0 + 3 * (f1 - f0) // 4, f1}:
        d = np.linalg.norm(coords(f) - base, axis=1)
        max_d = max(max_d, float(d.max()))
        mean_d = max(mean_d, float(d.mean()))
        moving = max(moving, float((d > 1e-4).mean()))
    res.update(verts=len(base), max_disp=round(max_d, 5), mean_disp=round(mean_d, 5), moving_frac=round(moving, 3))
    res["ok"] = max_d > 1e-4

print(json.dumps(res))
if JSON_OUT:
    with open(JSON_OUT, "w") as fh:
        json.dump(res, fh)
sys.exit(0 if res["ok"] else 1)
