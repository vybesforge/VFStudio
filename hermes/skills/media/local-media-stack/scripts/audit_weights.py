#!/usr/bin/env python3
"""Audit skin weights per height band on a GLB — catches legs claiming the body.

Usage:
    blender -b --python scripts/audit_weights.py -- model.glb [--leg-match _upper,_lower]

Answers the precise question "do leg bones still hold weight up on the back and
snout?". That failure looks like half the animal riding the legs and shearing
apart, and it is invisible to a group-name check because the groups exist.

Displacement spread is a muddier signal: a spine bob legitimately moves the upper
body non-uniformly, so a healthy rig still shows spread. Weight-per-band does not
have that ambiguity.
"""
import sys

import bpy

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
if not args:
    sys.exit("usage: ... -- model.glb [--leg-match _upper,_lower]")

path = args[0]
patterns = ("_upper", "_lower")
if "--leg-match" in args:
    patterns = tuple(
        p.strip() for p in args[args.index("--leg-match") + 1].split(",") if p.strip()
    )

top = 0.70  # height fraction above which leg influence must be ~zero

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=path)

meshes = [o for o in bpy.data.objects if o.type == "MESH"]
if not meshes:
    sys.exit("no mesh in GLB")
# A skinned GLB imports a stray tiny helper object first; take the real mesh.
obj = max(meshes, key=lambda o: len(o.data.vertices))
me = obj.data

leg_groups = {vg.index for vg in obj.vertex_groups
              if any(p in vg.name for p in patterns)}
print(f"[audit] mesh={obj.name} verts={len(me.vertices)} leg_groups={len(leg_groups)}")
if not leg_groups:
    print("[audit] no leg groups matched — check --leg-match")
    sys.exit(0)

zs = [v.co.z for v in me.vertices]
z0, z1 = min(zs), max(zs)
span = max(z1 - z0, 1e-9)

bands = {}
for v in me.vertices:
    h = (v.co.z - z0) / span
    w = sum(g.weight for g in v.groups if g.group in leg_groups)
    bands.setdefault(round(h, 1), []).append(w)

print("[audit] height band -> mean leg weight, max leg weight, count")
for key in sorted(bands):
    ws = bands[key]
    print(f"   {key:.1f}-{key + 0.1:.1f}: mean={sum(ws) / len(ws):.3f} "
          f"max={max(ws):.3f} n={len(ws)}")

above = [w for k, ws in bands.items() if k >= top for w in ws]
if above:
    peak = max(above)
    verdict = "CLEAN" if peak < 0.01 else "LEAKING"
    print(f"[audit] ABOVE {int(top * 100)}% height: max leg weight = {peak:.4f} ({verdict})")
    sys.exit(0 if peak < 0.01 else 1)
