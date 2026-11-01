#!/usr/bin/env python3
"""Prove a skinned GLB actually deforms, by measuring vertex motion.

Usage:
    blender -b --python scripts/test_deform.py -- model.glb [--frames 1,4,7,10]

Renders lie in both directions: a correctly skinned asset looked static from a
three-quarter view while 380k vertices were moving 0.33 m, and a rigid asset can
carry a full animation clip (clip count proves nothing). This evaluates the mesh
through the depsgraph and reports real displacement.

Exit code is 1 when nothing moves — a rig that does not deform is a failed run.
"""
import sys

import bpy
import numpy as np

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
if not args:
    sys.exit("usage: ... -- model.glb [--frames 1,4,7,10]")
path = args[0]
frames = [1, 4, 7, 10]
if "--frames" in args:
    frames = [int(x) for x in args[args.index("--frames") + 1].split(",") if x.strip()]

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=path)

meshes = [o for o in bpy.data.objects if o.type == "MESH"]
arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
if not meshes or not arms:
    sys.exit("missing mesh or armature — unskinned GLB")

# Importing a skinned GLB yields a stray small helper mesh first. Taking
# meshes[0] measures nothing and "proves" a working rig is broken.
obj = max(meshes, key=lambda o: len(o.data.vertices))
print(f"[test] candidates={[(o.name, len(o.data.vertices)) for o in meshes]}")
print(f"[test] using {obj.name} ({len(obj.data.vertices)} verts)")
print(f"[test] vertex_groups={len(obj.vertex_groups)}")
print(f"[test] modifiers={[(m.type, getattr(m, 'object', None) and m.object.name)
                        for m in obj.modifiers]}")
if not any(m.type == "ARMATURE" for m in obj.modifiers):
    print("[test] NO ARMATURE MODIFIER — the export carries no skin")

scene = bpy.context.scene


def sample(frame):
    scene.frame_set(frame)
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    pts = [v.co.copy() for v in me.vertices]
    ev.to_mesh_clear()
    return pts


samples = {f: sample(f) for f in frames}
base = samples[frames[0]]

zs = [v.z for v in base]
hip = min(zs) + 0.55 * (max(zs) - min(zs))
upper = [i for i, v in enumerate(base) if v.z > hip]
print(f"[test] upper-body verts={len(upper)}")

moved_any = False
for f in frames[1:]:
    deltas = [(a - b).length for a, b in zip(samples[f], base)]
    moved = sum(1 for d in deltas if d > 0.005)
    moved_any = moved_any or moved > 0
    print(f"[test] frame {f}: max_delta={max(deltas):.4f} m, verts_moved>5mm={moved}/{len(deltas)}")
    if upper:
        # Informational only: a spine bob legitimately moves the upper body
        # non-uniformly, so spread alone is not a pass/fail. Use
        # scripts/audit_weights.py for the real "legs claim the body" check.
        vecs = np.array([[samples[f][i].x - base[i].x,
                          samples[f][i].y - base[i].y,
                          samples[f][i].z - base[i].z] for i in upper])
        print(f"[test] frame {f}: upper-body displacement spread="
              f"{float(np.linalg.norm(vecs, axis=1).std()):.4f} m (informational)")

sys.exit(0 if moved_any else 1)
