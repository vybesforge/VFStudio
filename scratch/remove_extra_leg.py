"""Remove a spurious extra limb from a reconstruction.

TRELLIS produced a five-legged hog. Because every earlier measurement split the low
slab into four quadrants, the extra limb was invisible to it and the rig ended up with
a bone between two real legs — which is what rendered as a leg in the middle.

Strategy: rasterise the low slab, find connected columns, and if there are more than
four, delete the column nearest the middle of the body. Then cap the hole it leaves.

Usage:
  blender -b --python remove_extra_leg.py -- <src.glb> <dst.glb> [--keep 4]
"""
import sys

import bmesh
import bpy
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
SRC, DST = argv[0], argv[1]

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SRC)
obj = max([o for o in bpy.data.objects if o.type == "MESH"],
          key=lambda o: len(o.data.vertices))
for stray in [o for o in bpy.data.objects if o.type == "MESH" and o is not obj]:
    bpy.data.objects.remove(stray, do_unlink=True)

me = obj.data
co = np.array([v.co[:] for v in me.vertices], dtype=np.float64)
lo, hi = co.min(axis=0), co.max(axis=0)
size = hi - lo
L = 0 if size[0] >= size[1] else 1
W = 1 - L

up = (co[:, 2] - lo[2]) / size[2]
slab = (up >= 0.03) & (up <= 0.22)
pts = co[slab]

G = 90
ga = ((pts[:, L] - lo[L]) / size[L] * (G - 1)).astype(int)
gc = ((pts[:, W] - lo[W]) / size[W] * (G - 1)).astype(int)
grid = np.zeros((G, G), dtype=bool)
grid[ga, gc] = True

seen = np.zeros_like(grid)
comps = []
for i in range(G):
    for j in range(G):
        if not grid[i, j] or seen[i, j]:
            continue
        stack, cells = [(i, j)], []
        seen[i, j] = True
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
comps = [c for c in comps if len(c) > 25]      # ignore crumbs
print(f"[cut] {len(comps)} candidate limbs")

if len(comps) <= 4:
    print("[cut] four or fewer limbs — nothing to remove")
    bpy.ops.wm.save_as_mainfile(filepath="/tmp/_noop.blend")
    sys.exit(0)

centres = []
for cells in comps:
    arr = np.array(cells)
    centres.append((arr[:, 0].mean() / (G - 1), arr[:, 1].mean() / (G - 1), len(cells)))
    print(f"[cut]   limb along={centres[-1][0]:.3f} across={centres[-1][1]:.3f} cells={len(cells)}")

# The extra is the one closest to the body's mid-length but not at an end.
ordered = sorted(range(len(centres)), key=lambda k: centres[k][0])
middle = ordered[len(ordered) // 2]
extra = centres[middle]
print(f"[cut] removing limb at along={extra[0]:.3f} across={extra[1]:.3f}")

# Radius from the column's cell count, in normalised units, with a margin.
r_norm = float(np.sqrt(extra[2] / np.pi) / (G - 1)) * 2.0
print(f"[cut] cut radius {r_norm:.3f} (normalised)")

dL = (co[:, L] - lo[L]) / size[L] - extra[0]
dW = (co[:, W] - lo[W]) / size[W] - extra[1]
inside = (dL * dL + dW * dW) <= (r_norm * r_norm)
# only the limb itself, never the upper body
inside &= up <= 0.42
print(f"[cut] deleting {int(inside.sum())} vertices")

bm = bmesh.new()
bm.from_mesh(me)
bm.verts.ensure_lookup_table()
doomed = [bm.verts[i] for i in np.nonzero(inside)[0]]
bmesh.ops.delete(bm, geom=doomed, context="VERTS")

# Cap ONLY the socket left by the cut. The mesh has ~1,585 islands and over a hundred
# thousand boundary edges overall, so filling every boundary loop wrecks the surface.
bm.edges.ensure_lookup_table()
cut_centre = np.array([0.0, 0.0, 0.0])
cut_centre[L] = lo[L] + extra[0] * size[L]
cut_centre[W] = lo[W] + extra[1] * size[W]
cut_centre[2] = lo[2] + 0.10 * size[2]
reach = r_norm * 2.2

socket = []
for e in bm.edges:
    if len(e.link_faces) != 1:
        continue
    mid = (e.verts[0].co + e.verts[1].co) / 2
    if (mid - cut_centre).length <= reach * max(size[L], size[W]):
        socket.append(e)
if socket:
    bmesh.ops.holes_fill(bm, edges=socket, sides=0)
    print(f"[cut] capped {len(socket)} boundary edges around the socket only")
else:
    print("[cut] no socket boundary edges to cap")
bm.to_mesh(me)
bm.free()
me.update()

obj.select_set(True)
bpy.context.view_layer.objects.active = obj
bpy.ops.export_scene.gltf(filepath=DST, export_format="GLB", use_selection=True)
print(f"[cut] wrote {DST}")
print("done:")
