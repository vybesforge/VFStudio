"""Count distinct leg columns in the mesh — is there a 5th limb?

All prior measurement split the low slab into four quadrants, which would silently
hide an extra limb sitting in the middle. This rasterises the low slab and counts
connected columns instead, and also reports connected mesh components.
"""
import sys

import bpy
import numpy as np

path = sys.argv[-1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=path)

obj = max([o for o in bpy.data.objects if o.type == "MESH"],
          key=lambda o: len(o.data.vertices))
co = np.array([v.co[:] for v in obj.data.vertices], dtype=np.float64)
lo, hi = co.min(axis=0), co.max(axis=0)
size = hi - lo
L = 0 if size[0] >= size[1] else 1
W = 1 - L

up = (co[:, 2] - lo[2]) / size[2]
slab = (up >= 0.03) & (up <= 0.22)
pts = co[slab]
print(f"[legs] slab verts={len(pts)}")

# Rasterise in the horizontal plane.
G = 90
ga = ((pts[:, L] - lo[L]) / size[L] * (G - 1)).astype(int)
gc = ((pts[:, W] - lo[W]) / size[W] * (G - 1)).astype(int)
grid = np.zeros((G, G), dtype=bool)
grid[ga, gc] = True

# Flood fill 4-connected cells.
seen = np.zeros_like(grid)
comps = []
for i in range(G):
    for j in range(G):
        if not grid[i, j] or seen[i, j]:
            continue
        stack = [(i, j)]
        seen[i, j] = True
        cells = []
        while stack:
            a, b = stack.pop()
            cells.append((a, b))
            for da, db in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                na, nb = a + da, b + db
                if 0 <= na < G and 0 <= nb < G and grid[na, nb] and not seen[na, nb]:
                    seen[na, nb] = True
                    stack.append((na, nb))
        comps.append(cells)

comps.sort(key=len, reverse=True)
print(f"[legs] occupied-cell components: {len(comps)}")
for k, cells in enumerate(comps[:8]):
    arr = np.array(cells)
    ca, cc = arr[:, 0].mean(), arr[:, 1].mean()
    print(f"   comp{k}: cells={len(cells):4d} along={ca/(G-1):.3f} across={cc/(G-1):.3f}")

# Connected mesh components (a detached 5th limb shows up here too).
import bmesh
bm = bmesh.new()
bm.from_mesh(obj.data)
bm.verts.ensure_lookup_table()
seen_v = set()
islands = []
for v in bm.verts:
    if v.index in seen_v:
        continue
    stack = [v]
    seen_v.add(v.index)
    n = 0
    while stack:
        cur = stack.pop()
        n += 1
        for e in cur.link_edges:
            o = e.other_vert(cur)
            if o.index not in seen_v:
                seen_v.add(o.index)
                stack.append(o)
    islands.append(n)
islands.sort(reverse=True)
bm.free()
print(f"[legs] mesh islands: {len(islands)} sizes={islands[:8]}")
