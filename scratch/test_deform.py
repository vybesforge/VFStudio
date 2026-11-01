"""Prove whether a skinned GLB actually deforms, by measuring vertex motion.

Renders can lie (wrong frame mapping, NLA not evaluated, camera angle hiding the
swing). This evaluates the mesh through the depsgraph at two frames and reports
how far the vertices actually moved.
"""
import sys

import bpy

path = sys.argv[-1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=path)

meshes = [o for o in bpy.data.objects if o.type == "MESH"]
arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
print(f"[test] meshes={len(meshes)} armatures={len(arms)}")
if not meshes or not arms:
    sys.exit("missing mesh or armature")

obj = max(meshes, key=lambda o: len(o.data.vertices))
arm = arms[0]
stretch_report = True
print(f"[test] mesh candidates={[(o.name, len(o.data.vertices)) for o in meshes]}")
print(f"[test] using {obj.name} ({len(obj.data.vertices)} verts)")
print(f"[test] actions={[a.name for a in bpy.data.actions]}")
print(f"[test] modifiers={[(m.type, getattr(m, 'object', None) and m.object.name) for m in obj.modifiers]}")
print(f"[test] vertex_groups={len(obj.vertex_groups)}")

scene = bpy.context.scene


def sample(frame):
    scene.frame_set(frame)
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    pts = [v.co.copy() for v in me.vertices]
    ev.to_mesh_clear()
    return pts


frames = [1, 4, 7, 10]
samples = {f: sample(f) for f in frames}
base = samples[1]

# Upper body must move as one rigid piece. If leg bones are claiming back/snout
# vertices, the displacement vectors there differ wildly and the body tears.
zs = [v.z for v in base]
z0, z1 = min(zs), max(zs)
hip = z0 + 0.55 * (z1 - z0)
upper = [i for i, v in enumerate(base) if v.z > hip]
print(f"[test] upper-body verts: {len(upper)}")

import numpy as np
for f in frames[1:]:
    deltas = [(a - b).length for a, b in zip(samples[f], base)]
    mx = max(deltas)
    moved = sum(1 for d in deltas if d > 0.005)
    print(f"[test] frame {f}: max_delta={mx:.4f} m, verts_moved>5mm={moved}/{len(deltas)}")
    if upper:
        vecs = np.array([[samples[f][i].x - base[i].x,
                          samples[f][i].y - base[i].y,
                          samples[f][i].z - base[i].z] for i in upper])
        spread = float(np.linalg.norm(vecs, axis=1).std())
        print(f"[test] frame {f}: upper-body displacement spread={spread:.4f} m "
              f"({'RIGID/ok' if spread < 0.02 else 'SPLITTING'})")

# Head region: if the jaw/face is bound to a front leg, those vertices drift away
# from the rest of the head instead of moving with the body.
xs = [v.x for v in base]
ys = [v.y for v in base]
lax = 0 if (max(xs) - min(xs)) >= (max(ys) - min(ys)) else 1
lo_l = min(v[lax] for v in base)
hi_l = max(v[lax] for v in base)
leg_g = {vg.index for vg in obj.vertex_groups
         if "_upper" in vg.name or "_lower" in vg.name}
mesh_v = obj.data.vertices
head_sel = []
for i, v in enumerate(base):
    frac = (v[lax] - lo_l) / max(hi_l - lo_l, 1e-9)
    if frac <= 0.86:
        continue
    # Exclude actual leg geometry: the front-left leg sits at along 0.869, inside any
    # naive "front of the body" band, and measuring it as head is what made an earlier
    # version of this check report a false failure.
    legw = sum(g.weight for g in mesh_v[i].groups if g.group in leg_g)
    if legw > 0.1:
        continue
    head_sel.append(i)
print(f"[test] head-region verts: {len(head_sel)}")
if head_sel:
    for f in frames[1:]:
        vecs = np.array([[samples[f][i].x - base[i].x,
                          samples[f][i].y - base[i].y,
                          samples[f][i].z - base[i].z] for i in head_sel])
        spread = float(np.linalg.norm(vecs, axis=1).std())
        print(f"[test] frame {f}: head displacement spread={spread:.4f} m "
              f"({'HEAD STILL' if spread < 0.01 else 'HEAD MOVING WITH LEGS'})")

# Edge stretch: the direct measure of "smearing". Isolated vertices bound to the
# wrong bone are pulled far from their neighbours, so their edges stretch far beyond
# the rest length. Anything over ~2x is a visible streak.
if stretch_report:
    me = obj.data
    ed = np.empty(len(me.edges) * 2, dtype=np.int64)
    me.edges.foreach_get("vertices", ed)
    a_idx, b_idx = ed[0::2], ed[1::2]
    base_arr = np.array([[v.x, v.y, v.z] for v in samples[1]])
    rest = np.linalg.norm(base_arr[a_idx] - base_arr[b_idx], axis=1)
    keep = rest > 1e-5
    for f in frames[1:]:
        cur = np.array([[v.x, v.y, v.z] for v in samples[f]])
        now = np.linalg.norm(cur[a_idx[keep]] - cur[b_idx[keep]], axis=1)
        ratio = now / rest[keep]
        worst = float(ratio.max())
        bad = int((ratio > 2.0).sum())
        print(f"[test] frame {f}: max edge stretch={worst:.2f}x, edges>2x={bad} "
              f"({'CLEAN' if worst < 2.0 else 'SMEARING'})")
