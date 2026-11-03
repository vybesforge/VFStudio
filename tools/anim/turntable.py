"""turntable.py — render a GLB from N evenly spaced angles with Blender headless.

  bin/blender -b -P tools/anim/turntable.py -- model.glb outdir [--angles 8] [--res 640x900]

Why: a single-image mesh is only honest if you look at every side of it. The
front view is the one that was conditioned; the sides and back are the model's
invention, so they need eyes on them before anything ships.

Also dumps every image texture the GLB carries (base colour, metallic/roughness,
normal, AO) so the paint can be judged directly, not through the render.

Cycles on CPU (no display server → EEVEE has no GL context in headless mode).
"""
import math
import os
import sys

import bpy
from mathutils import Vector


def argv():
    a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    glb, outdir = a[0], a[1]
    rest = a[2:]
    angles = int(rest[rest.index("--angles") + 1]) if "--angles" in rest else 8
    res = rest[rest.index("--res") + 1] if "--res" in rest else "640x900"
    samples = int(rest[rest.index("--samples") + 1]) if "--samples" in rest else 32
    return glb, outdir, angles, res, samples


def clear():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def import_glb(path):
    bpy.ops.import_scene.gltf(filepath=path)
    objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not objs:
        raise SystemExit("no mesh imported from " + path)
    return objs


def bounds(objs):
    pts = []
    for o in objs:
        for c in o.bound_box:
            pts.append(o.matrix_world @ Vector(c))
    mn = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    mx = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return mn, mx


def setup_world(strength=0.75):
    w = bpy.data.worlds.new("W")
    bpy.context.scene.world = w
    w.use_nodes = True
    bg = w.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (0.05, 0.055, 0.06, 1)
    bg.inputs[1].default_value = strength


def add_lights(center, radius):
    specs = [((1.6, -2.2, 1.9), 900), ((-2.4, -1.2, 1.2), 350), ((0.2, 2.6, 1.6), 500)]
    for i, (pos, power) in enumerate(specs):
        d = bpy.data.lights.new(f"L{i}", type="AREA")
        d.energy = power * max(1.0, radius ** 2)
        d.size = radius * 1.4
        o = bpy.data.objects.new(f"L{i}", d)
        o.location = center + Vector(pos) * radius
        bpy.context.collection.objects.link(o)
        cons = o.constraints.new("TRACK_TO")
        cons.target = center_empty(center)
    # ground catch plane so the figure does not float
    bpy.ops.mesh.primitive_plane_add(size=radius * 12, location=(center.x, center.y, center.z - radius * 1.05))
    plane = bpy.context.object
    m = bpy.data.materials.new("ground")
    m.use_nodes = True
    m.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.10, 0.105, 0.11, 1)
    m.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.9
    plane.data.materials.append(m)


_EMPTY = {}


def center_empty(center):
    key = tuple(round(c, 5) for c in center)
    if key not in _EMPTY:
        e = bpy.data.objects.new("aim", None)
        e.location = center
        bpy.context.collection.objects.link(e)
        _EMPTY[key] = e
    return _EMPTY[key]


def main():
    glb, outdir, angles, res, samples = argv()
    os.makedirs(outdir, exist_ok=True)
    clear()
    objs = import_glb(glb)
    mn, mx = bounds(objs)
    center = (mn + mx) / 2
    size = (mx - mn)
    radius = max(size.x, size.y, size.z) * 1.05
    setup_world()
    add_lights(center, radius)

    W, H = (int(x) for x in res.lower().split("x"))
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = samples
    sc.cycles.use_denoising = True
    sc.render.resolution_x, sc.render.resolution_y = W, H
    sc.render.film_transparent = False
    # Standard, not AgX: AgX is a film look that desaturates hard, which makes an
    # honest texture look muddy and gets a good bake blamed for a render setting.
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.look = "None"
    sc.view_settings.exposure = 0.5

    cam_d = bpy.data.cameras.new("C")
    cam_d.lens = 60
    cam = bpy.data.objects.new("C", cam_d)
    bpy.context.collection.objects.link(cam)
    sc.camera = cam
    dist = radius * 2.35

    # aim the camera at chest height rather than the bbox centre
    aim = center + Vector((0, 0, size.z * 0.06))
    empty = center_empty(aim)
    cons = cam.constraints.new("TRACK_TO")
    cons.target = empty
    cons.track_axis = "TRACK_NEGATIVE_Z"
    cons.up_axis = "UP_Y"

    out = []
    for i in range(angles):
        yaw = 2 * math.pi * i / angles
        cam.location = Vector((math.sin(yaw) * dist, -math.cos(yaw) * dist, center.z + size.z * 0.22))
        name = f"view_{i * 360 // angles:03d}.png"
        sc.render.filepath = os.path.join(outdir, name)
        bpy.ops.render.render(write_still=True)
        out.append(sc.render.filepath)
        print("rendered", sc.render.filepath, flush=True)

    # dump the textures that came with the GLB
    texdir = os.path.join(outdir, "textures")
    os.makedirs(texdir, exist_ok=True)
    for img in bpy.data.images:
        if img.source in ("FILE", "GENERATED") and img.size[0] and img.name not in ("Render Result",):
            if img.packed_file or img.filepath:
                try:
                    p = os.path.join(texdir, f"{img.name.replace('/', '_')}.png")
                    img.filepath_raw = p
                    img.file_format = "PNG"
                    img.save()
                    print("texture", p, flush=True)
                except Exception as e:  # noqa: BLE001
                    print("texture-skip", img.name, e, flush=True)

    print("TRIS", sum(len(o.data.polygons) for o in objs),
          "VERTS", sum(len(o.data.vertices) for o in objs),
          "MATS", len({m.name for o in objs for m in o.data.materials if m}), flush=True)


main()
