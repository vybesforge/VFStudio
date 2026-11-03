import bpy, sys, math, os
from mathutils import Vector
argv = sys.argv[sys.argv.index("--")+1:]
src, outdir, frames = argv[0], argv[1], [int(x) for x in argv[2].split(",")]
os.makedirs(outdir, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
objs=[o for o in bpy.context.scene.objects if o.type=='MESH']
pts=[]
for o in objs:
    for c in o.bound_box: pts.append(o.matrix_world @ Vector(c))
mn=Vector((min(p.x for p in pts),min(p.y for p in pts),min(p.z for p in pts)))
mx=Vector((max(p.x for p in pts),max(p.y for p in pts),max(p.z for p in pts)))
c=(mn+mx)/2; span=max(mx.x-mn.x, mx.y-mn.y, mx.z-mn.z)
sc=bpy.context.scene
sc.render.engine='BLENDER_WORKBENCH'; sc.render.resolution_x=sc.render.resolution_y=640
sc.render.film_transparent=False
try:
    sh=sc.display.shading; sh.light='STUDIO'; sh.color_type='SINGLE'; sh.single_color=(0.62,0.64,0.68); sh.show_cavity=True; sh.cavity_type='BOTH'
except Exception as e: print('shading', e)
cd=bpy.data.cameras.new('c'); cd.type='ORTHO'; cd.ortho_scale=span*1.1
cam=bpy.data.objects.new('c',cd); sc.collection.objects.link(cam)
cam.location=c+Vector((1,0,0))*(span*3)
cam.rotation_euler=Vector((-1,0,0)).to_track_quat('-Z','Y').to_euler()
sc.camera=cam
for f in frames:
    sc.frame_set(f)
    sc.render.filepath=os.path.join(outdir, f"f{f:02d}.png")
    bpy.ops.render.render(write_still=True)
    print(f"[frames] wrote f{f:02d}.png")
