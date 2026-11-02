"""Render a GLB *with materials* (EEVEE) so a baked texture can actually be judged."""
import bpy, sys, os, math
from mathutils import Vector
argv = sys.argv[sys.argv.index("--")+1:]
src, out = argv[0], argv[1]
res = int(argv[2]) if len(argv) > 2 else 1024

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
pts = []
for o in objs:
    for c in o.bound_box:
        pts.append(o.matrix_world @ Vector(c))
mn = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
mx = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
c = (mn+mx)/2; span = max(mx.x-mn.x, mx.y-mn.y, mx.z-mn.z)

sc = bpy.context.scene
for eng in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "CYCLES"):
    try:
        sc.render.engine = eng; break
    except Exception:
        continue
sc.render.resolution_x = sc.render.resolution_y = res
sc.render.image_settings.file_format = "PNG"
sc.render.film_transparent = False
w = bpy.data.worlds.new("w"); sc.world = w
w.use_nodes = True
bg = w.node_tree.nodes.get("Background")
if bg:
    bg.inputs[0].default_value = (0.9, 0.9, 0.92, 1.0); bg.inputs[1].default_value = 1.6
sun_d = bpy.data.lights.new("sun", type="SUN"); sun_d.energy = 4.0
sun = bpy.data.objects.new("sun", sun_d); sc.collection.objects.link(sun)
sun.rotation_euler = (math.radians(55), 0, math.radians(35))

for name, axis in (("front", Vector((0, -1, 0))), ("side", Vector((1, 0, 0)))):
    cd = bpy.data.cameras.new(name); cd.type = "ORTHO"; cd.ortho_scale = span*1.05
    cam = bpy.data.objects.new(name, cd); sc.collection.objects.link(cam)
    cam.location = c + axis*(span*3)
    cam.rotation_euler = (-axis).to_track_quat("-Z", "Y").to_euler()
    sc.camera = cam
    sc.render.filepath = os.path.join(out, f"{name}.png")
    bpy.ops.render.render(write_still=True)
    print(f"[tex] {name}.png")
