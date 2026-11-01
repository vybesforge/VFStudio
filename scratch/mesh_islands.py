"""Report connected components of a GLB mesh, largest first.

TRELLIS occasionally emits stray shells alongside the subject. They inflate the
bounding box, which makes the texture stage sample a huge empty volume (hours per
step) and breaks any neck-based alignment. This finds the junk so it can be cut.

blender -b --python mesh_islands.py -- in.glb [out.glb keep_fraction]
"""
import sys
from collections import defaultdict

import bmesh
import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
SRC = argv[0]

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SRC)
ms = [o for o in bpy.context.scene.objects if o.type == "MESH"]
for o in ms:
    o.select_set(True)
bpy.context.view_layer.objects.active = ms[0]
if len(ms) > 1:
    bpy.ops.object.join()
obj = bpy.context.view_layer.objects.active

bm = bmesh.new()
bm.from_mesh(obj.data)
bm.verts.ensure_lookup_table()

parent = list(range(len(bm.verts)))


def find(a):
    while parent[a] != a:
        parent[a] = parent[parent[a]]
        a = parent[a]
    return a


def union(a, b):
    ra, rb = find(a), find(b)
    if ra != rb:
        parent[rb] = ra


for e in bm.edges:
    union(e.verts[0].index, e.verts[1].index)

groups = defaultdict(list)
for v in bm.verts:
    groups[find(v.index)].append(v)

sizes = sorted(((len(g), k) for k, g in groups.items()), reverse=True)
print(f"[islands] {len(groups)} components, {len(bm.verts)} verts")
total_bb = [obj.matrix_world @ v.co for v in bm.verts]
xs = [p.x for p in total_bb]; ys = [p.y for p in total_bb]; zs = [p.z for p in total_bb]
print(f"[islands] full bbox {max(xs)-min(xs):.3f} x {max(ys)-min(ys):.3f} x {max(zs)-min(zs):.3f}")

for n, k in sizes[:6]:
    g = groups[k]
    gx = [v.co.x for v in g]; gy = [v.co.y for v in g]; gz = [v.co.z for v in g]
    share = 100.0 * n / len(bm.verts)
    print(f"  {n:7d} verts ({share:5.1f}%)  bbox {max(gx)-min(gx):.3f} x {max(gy)-min(gy):.3f} x {max(gz)-min(gz):.3f}")

if len(argv) >= 3:
    OUT = argv[1]
    keep = float(argv[2]) if len(argv) > 2 else 0.99
    # Keep components until we cover `keep` of the verts (largest first).
    kept, acc = set(), 0
    for n, k in sizes:
        kept.add(k)
        acc += n
        if acc >= keep * len(bm.verts):
            break
    dead = [v for v in bm.verts if find(v.index) not in kept]
    print(f"[trim] removing {len(dead)} verts in {len(groups)-len(kept)} components")
    bmesh.ops.delete(bm, geom=dead, context="VERTS")
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    bpy.ops.export_scene.gltf(filepath=OUT, export_format="GLB", use_selection=False)
    print(f"[trim] wrote {OUT} verts={len(obj.data.vertices)}")
bm.free()
