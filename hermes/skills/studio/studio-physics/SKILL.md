---
name: studio-physics
description: "Use when a local game or shot needs gravity, collisions, rigid bodies, or a soft-body bake."
version: 1.0.0
author: Jimmy
license: Apache-2.0
platforms: [macos, linux, windows]
metadata:
  hermes:
    category: studio
    tags: [studio, physics, godot, blender, rigidbody, characterbody, threejs]
---

# studio-physics — local bodies, collisions, and bakes

Gameplay physics is the engine's own solver. This skill does not download a learned "physics model."
Godot for play. Three.js `src/sim.js` for a browser fall. Blender only to bake a shot.

Binary, every OS:

```bash
G="${GODOT:-$(command -v godot || command -v godot4 || echo /Applications/Godot.app/Contents/MacOS/Godot)}"
B="${BLENDER:-$(command -v blender || echo "$HOME/media-stack/bin/blender")}"
```

`$G` is Godot. `$B` is Blender (`bin/blender` finds the macOS app, then `blender` on `PATH`).

## When to Use

- A character should walk, jump, and land → Recipe 1 (already in the Godot templates).
- A prop should fall, bounce, or stack → Recipe 2.
- A pickup or trigger → Recipe 3.
- "Did the ray hit the floor?" → Recipe 4.
- A shot of tumbling boxes or a soft drop, baked in Blender → Recipe 5.
- A box falling in a web page → `studio-game` Recipe 8 (`src/sim.js`). Do not start Godot for that.

## Recipe 1 — CharacterBody (the templates)

2D: `game/templates/godot-2d/player.gd`. Gravity, jump, `move_and_slide()`.
3D: `game/templates/godot-3d/player.gd`. Same idea, plus mouse look.

Rules that already bit this stack:

- Call `move_and_slide()` once per `_physics_process`, not `_process`.
- Read `is_on_floor()` after `move_and_slide()`. The frame you spawn, it is often still false. The 2D self-test waits; the 3D template checks around frame 30.
- Spawn the body on the surface, not a pixel above it, or the first jumps fail.
- Do not set `velocity` and also `position` in the same tick. Let the slide move the body.

Headless proof (Godot installed):

```bash
"$G" --headless --path ~/media-stack/game/templates/godot-2d -- --selftest 2>&1 | grep 2D_SELFTEST
```

Expected: `2D_SELFTEST OK`.

## Recipe 2 — RigidBody3D drop

Intent: a crate that falls onto a static floor. Add this scene next to the 3D template's floor (`main.tscn` already has a `StaticBody3D`).

`crate.gd`:

```gdscript
extends RigidBody3D

func _ready() -> void:
    contact_monitor = true
    max_contacts_reported = 4
    body_entered.connect(func(other): print("CRATE_HIT ", other.name))
```

`crate.tscn` root is `RigidBody3D`, child `MeshInstance3D` (box) and `CollisionShape3D` (`BoxShape3D`, same size as the mesh). Mass 1. Gravity is the project default. Freeze the body (`freeze = true`) until the moment you want the drop, then set `freeze = false`.

Floor must be a `StaticBody3D` with a `CollisionShape3D`. A mesh with no shape is not a collider.

Layers: put the floor and the crate on layer 1, mask 1, unless you mean for them to miss each other.

## Recipe 3 — Area3D trigger

The 2D coin is the pattern (`coin.gd` / `coin.tscn`): an `Area3D` or `Area2D` in group `coins`, `body_entered` when the player overlaps, then `queue_free()` and a signal. Copy that. Do not use a `RigidBody` for a pickup that should not fall.

## Recipe 4 — RayCast3D

Child of the body, aimed down (`target_position = Vector3(0, -2, 0)`), `enabled = true`.

```gdscript
if $RayCast3D.is_colliding():
    print("RAY_HIT ", $RayCast3D.get_collider().name)
```

Use it for ground snaps and "what is in front of the camera." It does not move anything. For a one-shot query without a node, `PhysicsRayQueryParameters3D` plus `get_world_3d().direct_space_state.intersect_ray`.

## Recipe 5 — Blender rigid bake, optional soft body

Intent: a cube dropped onto a passive floor, stepped headless. No game runtime.

```bash
"$B" -b -P ~/media-stack/tools/physics/rigid_drop.py -- --frames 48
"$B" -b -P ~/media-stack/tools/physics/rigid_drop.py -- --soft --frames 24
```

Expected first line of the rigid run: `EULER_DROP landed=1` (the script's own integrator, so the check does not depend on a point-cache API). When Blender's solver evaluates, a second line `RIGID_BAKE z=<number>` appears and `z` is lower than the start (3). `--soft` prints `SOFT_STEP` instead of `RIGID_BAKE`. If the bake operator errors, the script prints `BAKE_SKIP` and still exits 0 after `EULER_DROP`. Fix the operator line it names; do not switch to a cloud physics API.

The scene is built in the script (empty file, ground, drop). It does not modify a caller's blend file. To bake a prop you already have, copy the rigid-body setup from the script onto that object and keep the same frame loop.

Soft body is the modifier path (`SOFT_BODY` plus collision on the ground). It is for a shot, not for a character controller. A playable character stays on Recipe 1.

## Pitfalls

- Godot 4's 3D default is `GodotPhysics`. Jolt is optional and not required by the templates. Do not flip `physics/3d/physics_engine` unless you have Jolt in that Godot build.
- `move_and_collide` stops at the first hit. `move_and_slide` is what the templates use for walking.
- A `RigidBody3D` ignores your `position` writes while unfrozen. Set `linear_velocity` or impulses.
- Three.js gravity in `src/sim.js` is not a collision solver. Two meshes can overlap. That is expected until you add a contact library on purpose.
- Blender's rigid-body point cache is easy to call wrong in `-b`. Trust `EULER_DROP` as the gate; treat `RIGID_BAKE` as the solver actually running.
