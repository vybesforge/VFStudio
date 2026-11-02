"""Headless drop: a cube falls onto a floor.

  blender -b -P tools/physics/rigid_drop.py -- --frames 48
  blender -b -P tools/physics/rigid_drop.py -- --soft --frames 24

Prints EULER_DROP always (explicit integrator). Prints RIGID_BAKE or SOFT_STEP
when Blender's solver evaluates, otherwise BAKE_SKIP. Does not save a file.
"""
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
soft = "--soft" in argv
frames = 48
if "--frames" in argv:
    frames = int(argv[argv.index("--frames") + 1])


def euler_landed(steps, dt=1.0 / 24.0):
    y, vy = 3.0, 0.0
    for _ in range(steps):
        vy -= 9.81 * dt
        y += vy * dt
        if y < 0.2:
            y, vy = 0.2, 0.0
            return 1
    return 0


print(f"EULER_DROP landed={euler_landed(frames)}", flush=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.frame_start = 1
scene.frame_end = frames
scene.gravity = (0.0, 0.0, -9.81)

bpy.ops.mesh.primitive_cube_add(size=4, location=(0, 0, -2))
ground = bpy.context.active_object
ground.name = "Ground"

bpy.ops.mesh.primitive_cube_add(size=0.4, location=(0, 0, 3))
body = bpy.context.active_object
body.name = "Drop"

try:
    if scene.rigidbody_world is None:
        bpy.ops.rigidbody.world_add()
    bpy.context.view_layer.objects.active = ground
    bpy.ops.rigidbody.object_add()
    ground.rigid_body.type = "PASSIVE"
    ground.rigid_body.collision_shape = "BOX"
    if soft:
        bpy.context.view_layer.objects.active = ground
        bpy.ops.object.modifier_add(type="COLLISION")
        bpy.context.view_layer.objects.active = body
        bpy.ops.object.modifier_add(type="SOFT_BODY")
        body.modifiers["Softbody"].settings.use_goal = False
    else:
        bpy.context.view_layer.objects.active = body
        bpy.ops.rigidbody.object_add()
        body.rigid_body.type = "ACTIVE"
        body.rigid_body.collision_shape = "BOX"
    world = scene.rigidbody_world
    world.point_cache.frame_start = 1
    world.point_cache.frame_end = frames
    for frame in range(1, frames + 1):
        scene.frame_set(frame)
    bpy.context.view_layer.update()
    z = body.matrix_world.translation.z
    label = "SOFT_STEP" if soft else "RIGID_BAKE"
    print(f"{label} z={z:.3f}", flush=True)
except Exception as exc:
    print(f"BAKE_SKIP {type(exc).__name__}: {exc}", flush=True)
