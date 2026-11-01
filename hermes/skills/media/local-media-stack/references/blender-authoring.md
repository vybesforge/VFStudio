# Blender authoring for generated assets (headless bpy)

Run headless via the wrapper (`~/media-stack/bin/blender -b --python script.py -- args`),
never through a symlink.

## Axis convention — the one that silently ruins a rig

**glTF is Y-up, but Blender's glTF importer converts to Z-up.** Inside a bpy
script the vertical axis is **Z**, and the two horizontal axes are X and Y.
Assuming Y-up places leg bones across the animal's width instead of under it, and
the result is a rig that deforms garbage while every number looks plausible.

Derive placement from the bounding box instead of hardcoding anatomy — image-to-3D
output has no fixed scale, orientation or proportions:

```python
bb = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
size = Vector((max(v.x for v in bb) - min(v.x for v in bb),
               max(v.y for v in bb) - min(v.y for v in bb),
               max(v.z for v in bb) - min(v.z for v in bb)))
length_axis = 0 if size.x >= size.y else 1   # travel axis (horizontal)
width_axis  = 1 if length_axis == 0 else 0
H = size.z                                    # up
```

## Weld before you separate

`bpy.ops.mesh.separate(type="LOOSE")` on a freshly imported GLB is meaningless:
the exporter splits vertices at every UV seam, so a clean 94k-tri mesh reports
**22,270 components**. Run `remove_doubles(threshold=0.0001)` first — then the
mesh collapses to 1 component and a genuinely separate backdrop/pedestal becomes
its own object you can actually identify and delete.

Any "drop the flat sheet" filter therefore belongs *after* welding. Before it,
you are classifying fragments.

## Blender 5.x API changes that break old snippets

- **`Action.fcurves` is gone** (slotted actions). Iterate
  `action.layers → layer.strips → strip.channelbags → channelbag.fcurves`. Guard
  with `try/except AttributeError` so the script still exports on older builds.
- `use_nodes` on materials/worlds emits a removal deprecation (6.0); harmless, but
  do not build logic on it.
- Passing a relative `scene.render.filepath` fails with
  `cannot save: 'file.png'` — always use an absolute path.

## Rigging a quadruped that has no skeleton

1. Build the armature in edit mode with a spine chain plus four legs (upper +
   lower per leg). **Count the limbs first and place bones from measured positions,
   never bbox fractions** — bbox fractions put bones outside the legs, and no
   weighting scheme compensates for a bone that is not inside the limb it drives.
2. Bind with `bpy.ops.object.parent_set(type="ARMATURE_AUTO")`.
3. **Verify the bind by counting real weights, not group names.** Bone-heat
   weighting prints `Bone Heat Weighting: failed to find solution for one or more
   bones` and still returns success. Worse, it leaves the vertex groups **present
   but empty**, so comparing bone names against `obj.vertex_groups` passes while
   the exporter writes `Mesh_0 has no skin` — the GLB then carries animation
   curves and never deforms. Count vertices with `weight > 1e-5` per bone and, if
   any bone is empty, run `proximity_weights()` (nearest bone-segment, two-bone
   blend) rather than falling back to `ARMATURE_ENVELOPE`, which binds unevenly on
   a dense organic mesh.
4. Keyframe a trot: diagonal pairs (`FL`+`BR` vs `FR`+`BL`) in antiphase, upper
   bone swinging ±20°, lower bone flexing, plus a small root bob. Four keys per
   leg per cycle reads as a walk at 24 frames.
5. **Swing limbs about a world axis converted into bone space.** `rotation_euler.x`
   on a leg bone rotates about the bone's local X, which follows roll — undefined
   unless set — and splays the legs sideways instead of fore/aft. Use
   `local_axis = pb.bone.matrix_local.to_3x3().inverted() @ world_axis` with
   `rotation_mode = 'QUATERNION'`.

## Nearest-bone weighting lets legs claim the body

Plain point-to-segment binding has no notion of anatomy: a long leg segment is
closer to the snout and the back than a short spine bone is, so the legs win those
vertices and the body shears apart as the legs swing. The user-visible symptom is
"half the animal moves with the legs / the back and snout split".

Gate it in two places — **both are required**:

1. **Region gate.** A leg bone may only claim vertices below the hip line and on
   its own longitudinal half and lateral side. With hips at 52% of height, ramp the
   leg weight to zero across a band around that line so the transition blends
   instead of tearing:

   ```python
   ramp = np.clip((hip_z + band - up) / band, 0.0, 1.0)   # up = normalised height
   d[:, leg_j] = np.where(same_half & same_side, d[:, leg_j], np.inf)
   ```

2. **Damp the second-nearest bone too.** Damping only the nearest bone leaves
   vertices whose nearest is the spine but whose *second* is a leg holding up to
   0.5 leg weight high on the back — measured 0.27 above 70% height. Subtract the
   damped remainder on **both** the primary and secondary assignment and add it to
   the spine group.

Verify with a per-height-band audit: leg weight above 70% height must be ~0. Do
**not** use upper-body displacement spread as the pass/fail on its own — a spine
bob legitimately moves the upper body non-uniformly, so a healthy rig still shows
a few centimetres of spread.

## Keep leg capture out of the head (jaw/mouth riding the walk)

The snout and lower jaw hang **low and forward**, which puts them inside the front
legs' capture cylinder even when the hip-line ramp is correct. The symptom is the
mouth swinging with the stride.

Two gates, both needed:

1. **No leg may claim anything forward of the front legs.**
   `head_along = front_leg_along + 0.03`, then zero leg weight above that line.
2. **Lock head-region islands to body bones outright.** For islands whose centroid
   lies forward of that line, zero the leg columns in the island score matrix before
   `argmax`, so a leg can never win on raw distance.

**Place the gate forward of the legs, not at the neck.** The neck sits around
0.84 along while a front leg can sit at 0.87 — a neck-based gate locks the front leg
out of leg binding (one upper-leg group collapsed to 273 verts out of ~10,000) and
starves the very limb it was meant to leave alone. The boundary must be clear of the
front leg columns.

## Verify the gate itself before trusting its verdict

Every locality check here can silently measure the wrong thing, and a broken metric
makes a good fix look like a failure. Confirmed traps from this mesh family:

- A "head region" selected as `along > 0.86` **includes the front-left leg at 0.869**,
  so it reports `HEAD MOVING WITH LEGS` no matter what you change. Exclude vertices
  whose leg-bone weight exceeds ~0.1 from any head/face metric.
- An end-of-body audit labelled one end `FACE`, but both ends of a quadruped carry
  legs, so it reported `LEAKING at 1.0000` on a healthy asset.
- A height-histogram pedestal check contradicted a clean render.

**Rule: when a locality gate appears not to work, first ask whether the gate line
cuts through the thing it is supposed to protect.** Re-derive the boundary from
measured geometry (front-leg column centroids), then re-measure. Report a metric's
value only after confirming what its selection actually contains.

## Count limbs, never quadrant-split

A fixed four-quadrant split of the underside **cannot see a fifth limb**: the extra
one lands inside a quadrant, its centroid is averaged with the real leg's, and the
rig then places a bone between two legs. The user-visible result is "an extra leg in
the middle" while every printed coordinate looks plausible.

Rasterise the low slab and count connected columns instead:

```python
slab = (up >= 0.03) & (up <= 0.22)      # up = normalised height; ankle zone
pts = co[slab]
G = 90
ga = ((pts[:, L] - lo[L]) / size[L] * (G - 1)).astype(int)
gc = ((pts[:, W] - lo[W]) / size[W] * (G - 1)).astype(int)
grid = np.zeros((G, G), bool); grid[ga, gc] = True
# flood-fill 4-connected occupied cells; each component is one limb
```

Place leg bones at those component centroids. `scripts/count_legs.py` ships with
this skill and reports both the column count and the island sizes — run it before
rigging any new reconstruction.

## Removing a spurious limb

Generators add limbs; delete the extra rather than rigging around it.

- Identify the surplus component as the one nearest mid-length (`along` between the
  real front and rear pairs), then delete vertices inside a disk around its centroid,
  capped in height (`up <= 0.42`) so the torso survives.
- **Cap only the socket you cut.** This mesh family is ~1,500 islands with over
  100,000 boundary edges overall, so `bmesh.ops.holes_fill` across *all* boundary
  edges rebuilds faces over the whole surface and wrecks it. Filter to boundary
  edges whose midpoint lies within ~2× the cut radius of the socket centre, and fill
  only those.
- Re-run the column count afterwards: it must drop to exactly four.

`scratch/remove_extra_leg.py` implements detection, cut and socket cap.

## Island-rigid skinning is what stops the smearing

Image-to-3D output is a **soup of loose islands** (this family: ~1,585 islands,
median 47 verts). Per-vertex weighting tears wherever one island spans two bones,
and the result reads as geometry smeared across the screen. Smoothing does not fix
it — it spreads the bad weights around. Measured on one 700k-tri asset:

| approach | max edge stretch | edges >2x |
|---|---|---|
| nearest bone | 123.5x | 3,905 |
| + Laplacian smoothing + far-bone cutoff | 32.0x | 5,212 |
| parametric limb cylinders | 29.3x | 4,979 |
| **island-rigid** | **1.00x** | **0** |

Bind each island wholesale to its dominant bone — the one that accumulated the most
weight across that island:

```python
parent = np.arange(len(co))
for u, v in zip(e0, e1):                     # union-find over mesh edges
    ru, rv = find(u), find(v)
    if ru != rv: parent[rv] = ru
scores = np.zeros((n_islands, len(bones)))
np.add.at(scores, island, W)                 # W = any per-vertex weight estimate
dominant = scores.argmax(axis=1)
W[:] = 0; W[np.arange(len(co)), dominant[island]] = 1.0
```

State the trade-off plainly: joints no longer bend smoothly — limbs move as rigid
chunks. That beats tearing, and soft bending needs a welded or retopologised mesh,
which is a separate job. Do not promise both from one pass.

## Gate smearing on edge stretch, not on renders or displacement spread

A vertex bound to the wrong bone is pulled away from its neighbours, so its edges
stretch far past rest length. That is the defect and it has a number:

```python
rest = np.linalg.norm(base[a_idx] - base[b_idx], axis=1)
now  = np.linalg.norm(cur[a_idx]  - cur[b_idx],  axis=1)
ratio = now / rest
print(ratio.max(), (ratio > 2.0).sum())      # want ~1.0x and 0
```

`scripts/test_deform.py` prints this per frame. On an island-rigid asset ignore
"upper-body displacement spread" — it now measures how rigidly different islands
sit, not surface tearing.

## Exporting animation

```python
bpy.ops.export_scene.gltf(
    filepath=DST, export_format="GLB", use_selection=True,
    export_animations=True, export_frame_range=True,
    export_anim_single_armature=True, export_skins=True,
    export_materials="EXPORT",
)
```

A skinned, animated GLB gains `JOINTS_0` and `WEIGHTS_0`; the presence of those
attributes plus `animations > 0` is the cheap proof it actually exported (the QC
gate reports both).

## Comparing two assets honestly

Render both from a **fixed camera derived from the bbox**, not by eye:
position the camera at a constant multiple of the asset's span, aim with
`direction.to_track_quat("-Z", "Y")`, add the same key/fill lights and a ground
plane. Two renders from different angles will fool you into judging the camera,
not the substance. Add a top-down mode — a silhouette defect that is invisible in a
three-quarter view is obvious from above.
