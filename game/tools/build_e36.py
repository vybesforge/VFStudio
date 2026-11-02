"""
build_e36.py — procedural BMW E36 sedan for Crossing (Blender 5.x, headless).

Usage:
  blender -b -P build_e36.py -- [--out /path/e36.glb] [--render /path/prefix]

Geometry is authored in real E36 dimensions (mm->m): length 4.43, width 1.71,
height 1.39, wheelbase 2.70, track 1.47, 205/60R15 -> r 0.31 m.
Blender +Y = nose  ->  glTF -Z = Godot forward.
"""
import bpy, bmesh, math, sys, os
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
def arg(name, default=None):
    if name in argv:
        return argv[argv.index(name) + 1]
    return default

OUT = arg("--out", os.path.expanduser("~/media-stack/game/crossing/assets/e36.glb"))
RENDER = arg("--render", None)

# ---------------------------------------------------------------- scene reset
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

# ---------------------------------------------------------------- materials
def mat(name, color, rough=0.5, metal=0.0, alpha=1.0, emit=None, emit_strength=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*color, 1.0)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    if alpha < 1.0:
        b.inputs["Alpha"].default_value = alpha
        m.blend_method = 'BLEND'
    if emit is not None:
        b.inputs["Emission Color"].default_value = (*emit, 1.0)
        b.inputs["Emission Strength"].default_value = emit_strength
    return m

M_PAINT  = mat("E36_Paint",   (0.082, 0.112, 0.145), rough=0.46, metal=0.18)
M_TRIM   = mat("E36_Trim",    (0.021, 0.022, 0.024), rough=0.78)
M_GLASS  = mat("E36_Glass",   (0.020, 0.026, 0.034), rough=0.10, alpha=0.55)
M_CHROME = mat("E36_Chrome",  (0.62, 0.63, 0.65),    rough=0.28, metal=1.0)
M_RUBBER = mat("E36_Rubber",  (0.016, 0.016, 0.017), rough=0.92)
M_RIM    = mat("E36_Rim",     (0.44, 0.45, 0.47),    rough=0.34, metal=0.9)
M_LAMP   = mat("E36_Lamp",    (0.95, 0.92, 0.80),    rough=0.15, emit=(1.0, 0.94, 0.78), emit_strength=2.2)
M_TAIL   = mat("E36_Tail",    (0.45, 0.03, 0.02),    rough=0.30, emit=(0.75, 0.05, 0.03), emit_strength=1.3)
M_UNDER  = mat("E36_Under",   (0.014, 0.014, 0.015), rough=0.95)

# ---------------------------------------------------------------- helpers
def new_obj(name, bm, materials):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for m in materials:
        me.materials.append(m)
    ob = bpy.data.objects.new(name, me)
    scene.collection.objects.link(ob)
    return ob

def section(w, zb, zt, n=4.6, steps=28, wt=None):
    """Closed rounded-rectangle (superellipse) ring in the XZ plane.
    `wt` (optional) tapers the half-width from `w` at zb to `wt` at zt (tumblehome)."""
    pts = []
    zc = (zb + zt) * 0.5
    hz = (zt - zb) * 0.5
    e = 2.0 / n
    wt = w if wt is None else wt
    for i in range(steps):
        t = 2.0 * math.pi * i / steps
        c, s = math.cos(t), math.sin(t)
        z = zc + hz * math.copysign(abs(s) ** e, s)
        f = 0.0 if zt == zb else (z - zb) / (zt - zb)
        ww = w + (wt - w) * f
        x = ww * math.copysign(abs(c) ** e, c)
        pts.append((x, z))
    return pts

def loft(name, stations, material, steps=28, cap=True, n=4.6):
    """stations: (y, half_width, z_bottom, z_top) or (y, w_bottom, w_top, z_bottom, z_top)."""
    bm = bmesh.new()
    rings = []
    for st in stations:
        if len(st) == 5:
            y, wb, wt, zb, zt = st
        else:
            y, wb, zb, zt = st
            wt = wb
        ring = [bm.verts.new((x, y, z)) for (x, z) in section(wb, zb, zt, n, steps, wt)]
        rings.append(ring)
    for a, b in zip(rings, rings[1:]):
        for j in range(len(a)):
            k = (j + 1) % len(a)
            bm.faces.new((a[j], a[k], b[k], b[j]))
    if cap:
        bm.faces.new(list(reversed(rings[0])))
        bm.faces.new(rings[-1])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return new_obj(name, bm, [material])

def add_box(name, center, size, material, rot=None):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = Vector((v.co.x * size[0], v.co.y * size[1], v.co.z * size[2]))
    ob = new_obj(name, bm, [material])
    ob.location = Vector(center)
    if rot:
        ob.rotation_euler = rot
    return ob

def add_cylinder(name, center, radius, depth, material, axis='Z', verts=24):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=verts,
                          radius1=radius, radius2=radius, depth=depth)
    ob = new_obj(name, bm, [material])
    ob.location = Vector(center)
    if axis == 'X':
        ob.rotation_euler = (0, math.radians(90), 0)
    elif axis == 'Y':
        ob.rotation_euler = (math.radians(90), 0, 0)
    return ob

def quad(name, corners, material):
    bm = bmesh.new()
    vs = [bm.verts.new(c) for c in corners]
    bm.faces.new(vs)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return new_obj(name, bm, [material])

# ---------------------------------------------------------------- body
# (y, w_bottom, w_top, z_bottom, z_top) — nose is +Y
LOWER = [
    (-2.215, 0.700, 0.762, 0.315, 0.720),
    (-2.140, 0.795, 0.822, 0.250, 0.780),
    (-2.020, 0.830, 0.852, 0.215, 0.818),
    (-1.780, 0.845, 0.860, 0.190, 0.848),
    (-1.400, 0.848, 0.862, 0.180, 0.864),
    (-0.900, 0.850, 0.864, 0.176, 0.874),
    (-0.300, 0.850, 0.864, 0.176, 0.876),
    ( 0.300, 0.847, 0.861, 0.178, 0.872),
    ( 0.780, 0.838, 0.850, 0.182, 0.860),
    ( 1.180, 0.828, 0.840, 0.190, 0.844),
    ( 1.640, 0.815, 0.827, 0.205, 0.828),
    ( 1.980, 0.805, 0.816, 0.235, 0.804),
    ( 2.150, 0.775, 0.795, 0.280, 0.776),
    ( 2.215, 0.700, 0.735, 0.330, 0.718),
]
body = loft("E36_Body", list(reversed(LOWER)), M_PAINT, n=5.2)

# cylinder cutters for the wheel arches
cutters = []
for (y, x) in ((1.350, 0.735), (1.350, -0.735), (-1.350, 0.735), (-1.350, -0.735)):
    c = add_cylinder("cut", (x * 1.02, y, 0.315), 0.395, 0.42, M_TRIM, axis='X', verts=32)
    cutters.append(c)
bpy.context.view_layer.objects.active = body
body.select_set(True)
for c in cutters:
    m = body.modifiers.new("arch", 'BOOLEAN')
    m.object = c
    m.operation = 'DIFFERENCE'
    with bpy.context.temp_override(object=body, active_object=body):
        bpy.ops.object.modifier_apply(modifier="arch")
for c in cutters:
    bpy.data.objects.remove(c, do_unlink=True)
body.select_set(False)

# ---------------------------------------------------------------- greenhouse
# tapered greenhouse (tumblehome) + raked backlight; roof ends ~y=-1.10
CABIN = [
    ( 0.985, 0.662, 0.622, 0.790, 0.900),
    ( 0.880, 0.680, 0.612, 0.790, 0.985),
    ( 0.700, 0.700, 0.616, 0.790, 1.130),
    ( 0.480, 0.715, 0.626, 0.790, 1.280),
    ( 0.330, 0.722, 0.640, 0.790, 1.368),
    ( 0.050, 0.726, 0.647, 0.790, 1.390),
    (-0.500, 0.724, 0.650, 0.790, 1.392),
    (-0.900, 0.716, 0.642, 0.790, 1.384),
    (-1.100, 0.700, 0.632, 0.790, 1.330),
    (-1.300, 0.676, 0.612, 0.790, 1.140),
    (-1.480, 0.650, 0.592, 0.790, 0.960),
    (-1.600, 0.620, 0.572, 0.790, 0.880),
]
cabin = loft("E36_Cabin", list(reversed(CABIN)), M_PAINT, n=4.2)

# ---------------------------------------------------------------- glass (tilted to follow tumblehome)
quad("E36_Windshield", [(-0.664, 0.952, 0.912), (0.664, 0.952, 0.912),
                        (0.638, 0.352, 1.342), (-0.638, 0.352, 1.342)], M_GLASS)
quad("E36_RearWindow", [(-0.640, -1.352, 1.212), (0.640, -1.352, 1.212),
                        (0.616, -1.598, 0.898), (-0.616, -1.598, 0.898)], M_GLASS)
for s in (1, -1):
    # front door glass: bottom x 0.724 @z0.86 -> top x 0.660 @z1.35
    quad(f"E36_SideWin_F{s}", [(s * 0.700, 0.300, 1.344), (s * 0.722, -0.320, 1.352),
                               (s * 0.724, -0.320, 0.850), (s * 0.722, 0.290, 0.850)], M_GLASS)
    quad(f"E36_SideWin_R{s}", [(s * 0.712, -0.372, 1.350), (s * 0.678, -1.086, 1.300),
                               (s * 0.700, -1.086, 0.850), (s * 0.724, -0.372, 0.850)], M_GLASS)

# ---------------------------------------------------------------- wheels
def wheel(name, x, y):
    bm = bmesh.new()
    # tyre: lathe a rounded profile around the X axis, capped both sides
    prof = [(0.248, -0.102), (0.292, -0.100), (0.311, -0.068),
            (0.311, 0.068), (0.292, 0.100), (0.248, 0.102)]
    rings = []
    for (r, dx) in prof:
        ring = []
        for i in range(32):
            t = 2 * math.pi * i / 32
            ring.append(bm.verts.new((dx, r * math.cos(t), r * math.sin(t))))
        rings.append(ring)
    for a, b in zip(rings, rings[1:]):
        for j in range(32):
            k = (j + 1) % 32
            bm.faces.new((a[j], a[k], b[k], b[j]))
    bm.faces.new(list(reversed(rings[0])))
    bm.faces.new(rings[-1])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    tyre = new_obj(name + "_tyre", bm, [M_RUBBER])
    # rim face + spokes sit just proud of the outer sidewall so they read at distance
    rim = add_cylinder(name + "_rim", (0.104, 0, 0), 0.183, 0.022, M_RIM, axis='X', verts=32)
    hub = add_cylinder(name + "_hub", (0.112, 0, 0), 0.055, 0.020, M_CHROME, axis='X', verts=20)
    spokes = []
    for i in range(5):
        a = 2 * math.pi * i / 5
        sp = add_box(name + f"_spoke{i}", (0.112, 0.090 * math.cos(a), 0.090 * math.sin(a)),
                     (0.020, 0.120, 0.032), M_RIM, rot=(a, 0, 0))
        spokes.append(sp)
    parts = [tyre, rim, hub] + spokes
    bpy.ops.object.select_all(action='DESELECT')
    for p in parts:
        p.select_set(True)
    bpy.context.view_layer.objects.active = tyre
    with bpy.context.temp_override(active_object=tyre, selected_objects=parts,
                                   selected_editable_objects=parts):
        bpy.ops.object.join()
    tyre.name = name
    if x < 0:  # mirror so the rim face points outboard on the left side
        tyre.rotation_euler = (0, 0, math.pi)
    tyre.location = (x, y, 0.310)
    return tyre

# ---------------------------------------------------------------- lamps, trim
for s_ in (1, -1):
    # E36 quad headlights: two round lamps per side, sitting proud of the nose
    add_box(f"E36_LampBox_{s_}", (s_ * 0.520, 2.214, 0.618), (0.400, 0.040, 0.190), M_TRIM)
    for i, dx in enumerate((-0.098, 0.098)):
        add_cylinder(f"E36_Head_{s_}_{i}", (s_ * 0.520 + dx, 2.238, 0.622),
                     0.082, 0.026, M_LAMP, axis='Y', verts=22)
    add_box(f"E36_Indicator_{s_}", (s_ * 0.700, 2.224, 0.612), (0.130, 0.030, 0.115), M_LAMP)
    # kidney grille halves + surround
    add_box(f"E36_Kidney_{s_}", (s_ * 0.086, 2.226, 0.628), (0.150, 0.030, 0.210), M_CHROME)
    add_box(f"E36_GrilleBar", (0.0, 2.230, 0.628), (0.030, 0.030, 0.215), M_PAINT)
    # tail lights
    add_box(f"E36_Tail_{s_}", (s_ * 0.575, -2.232, 0.672), (0.330, 0.036, 0.165), M_TAIL)
    add_box(f"E36_TailInner_{s_}", (s_ * 0.310, -2.230, 0.672), (0.190, 0.030, 0.120), M_TAIL)
    # side mirrors
    add_box(f"E36_Mirror_{s_}", (s_ * 0.800, 0.760, 1.010), (0.130, 0.068, 0.072), M_TRIM)
    add_box(f"E36_MirrorArm_{s_}", (s_ * 0.752, 0.800, 0.962), (0.080, 0.040, 0.048), M_TRIM)
    # door handles, rubbing strip, sill
    add_box(f"E36_Handle_{s_}", (s_ * 0.867, 0.060, 0.782), (0.012, 0.140, 0.030), M_CHROME)
    add_box(f"E36_HandleR_{s_}", (s_ * 0.867, -0.760, 0.782), (0.012, 0.140, 0.030), M_CHROME)
    add_box(f"E36_Strip_{s_}", (s_ * 0.862, -0.100, 0.560), (0.014, 3.10, 0.045), M_TRIM)
    add_box(f"E36_Sill_{s_}", (s_ * 0.842, -0.150, 0.196), (0.024, 2.20, 0.055), M_TRIM)
# low air intake between the kidneys
add_box("E36_Intake", (0, 2.222, 0.470), (0.560, 0.030, 0.110), M_TRIM)
# bumpers
add_box("E36_BumperF", (0, 2.196, 0.415), (1.640, 0.070, 0.190), M_TRIM)
add_box("E36_BumperR", (0, -2.204, 0.430), (1.600, 0.070, 0.190), M_TRIM)
add_box("E36_LipF", (0, 2.170, 0.318), (1.480, 0.090, 0.075), M_TRIM)
add_box("E36_PlateF", (0, 2.236, 0.470), (0.340, 0.016, 0.120), M_CHROME)
add_box("E36_Under", (0, 0.0, 0.138), (1.400, 3.78, 0.040), M_UNDER)
add_cylinder("E36_Exhaust", (-0.560, -2.240, 0.330), 0.038, 0.160, M_CHROME, axis='Y', verts=14)

# wipers parked on the cowl
for s_ in (1, -1):
    add_box(f"E36_Wiper_{s_}", (s_ * 0.290, 0.990, 0.892), (0.420, 0.018, 0.012), M_TRIM,
            rot=(0, 0, math.radians(7 * s_)))

wheels = [wheel("Wheel_FL", -0.735, 1.350), wheel("Wheel_FR", 0.735, 1.350),
          wheel("Wheel_RL", -0.735, -1.350), wheel("Wheel_RR", 0.735, -1.350)]

# ---------------------------------------------------------------- shading
for ob in [o for o in scene.objects if o.type == 'MESH']:
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob

all_meshes = [o for o in scene.objects if o.type == 'MESH']
bpy.ops.object.select_all(action='DESELECT')
for o in all_meshes:
    o.select_set(True)
try:
    bpy.ops.object.shade_auto_smooth(angle=math.radians(38))
except Exception as e:
    print("auto_smooth fallback:", e)
    bpy.ops.object.shade_smooth()
bpy.ops.object.select_all(action='DESELECT')

# ---------------------------------------------------------------- render check
if RENDER:
    cam_data = bpy.data.cameras.new("Cam")
    cam_data.lens = 62
    cam = bpy.data.objects.new("Cam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", 'SUN'))
    sun.data.energy = 4.0
    sun.data.angle = math.radians(3)
    sun.rotation_euler = (math.radians(62), 0, math.radians(38))
    scene.collection.objects.link(sun)
    fill = bpy.data.objects.new("Fill", bpy.data.lights.new("Fill", 'AREA'))
    fill.data.energy = 900
    fill.data.size = 6
    fill.location = (-5, -4, 4)
    fill.rotation_euler = (math.radians(55), 0, math.radians(-40))
    scene.collection.objects.link(fill)
    world = bpy.data.worlds.new("W")
    scene.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.25, 0.28, 0.33, 1)
    world.node_tree.nodes["Background"].inputs[1].default_value = 1.0
    gnd = add_box("Ground", (0, 0, -0.02), (40, 40, 0.04), mat("gnd", (0.2, 0.2, 0.2)))
    scene.render.engine = 'BLENDER_EEVEE'
    scene.render.resolution_x, scene.render.resolution_y = 960, 540
    scene.render.film_transparent = False
    views = {
        "front34": ((4.4, 5.0, 1.9), (0, 0.4, 0.72)),
        "rear34": ((-4.2, -5.2, 2.0), (0, -0.4, 0.72)),
        "side":    ((8.6, 0.2, 1.35), (0, 0.0, 0.72)),
        "front":   ((0.9, 7.4, 1.15), (0, 1.6, 0.66)),
    }
    for name, (loc, look) in views.items():
        cam.location = Vector(loc)
        d = Vector(look) - Vector(loc)
        cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
        scene.render.filepath = f"{RENDER}_{name}.png"
        bpy.ops.render.render(write_still=True)
    bpy.data.objects.remove(gnd, do_unlink=True)

# ---------------------------------------------------------------- export
bpy.ops.object.select_all(action='SELECT')
os.makedirs(os.path.dirname(OUT), exist_ok=True)
bpy.ops.export_scene.gltf(filepath=OUT, export_format='GLB', use_selection=False,
                          export_apply=True, export_yup=True)
print("E36_OK", OUT, os.path.getsize(OUT), "bytes")
