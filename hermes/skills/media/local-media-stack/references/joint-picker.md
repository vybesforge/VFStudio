# Joint picker: let this user place the joints, then build the rig

Automatic rigging is the weak link on reconstructed meshes, and it is weak
structurally rather than tunably: the legs are not symmetric (measured rear-left
0.467 vs rear-right 0.380, front 0.849/0.820 on one asset) and the generator can add
a limb. No bbox rule produces that. This user's own proposal — "if you made the
model and paint, then gave me a way to select the joints" — is the right shape, so
**offer hand-placed joints instead of iterating weighting heuristics.**

## Architecture (all local, single origin)

    browser picker  ──POST /api/rig/joints──▶  rig/joints_<asset>.json
          │                                          │
          └──POST /api/rig/build──────────────────▶ blender -b rig_from_joints.py
                                                     └─▶ vr/hog_rigged.glb

- `vr/rig.html` — standalone Three.js picker.
- The same panel is embedded in the room (`vr/index.html`, a `Rig` button) so it
  works on **whatever asset is loaded**, not just today's mesh. This user asked for
  that explicitly: "bake this into our VR room as well for assets that are loaded,
  and need adjusting for future projects." Tools belong in the one origin, never a
  second port.
- Panel endpoints in `control/panel.py`: `GET /api/rig/assets`,
  `GET|POST /api/rig/joints`, `POST /api/rig/build`, `GET /api/rig/build/status`.
- **Store joints per asset** (`rig/joints_<slug>.json`), not in one shared file, so
  a new project starts from a clean slate instead of inheriting the previous
  animal's anatomy.

## Coordinate spaces — the part that silently breaks

Joints are picked in the **asset's own glTF space (Y-up)** and consumed by Blender
**Z-up**. Convert exactly once, in the Blender script:

```python
J[name] = Vector((p["x"], -p["z"], p["y"])) * scale_factor
```

and back the other way when seeding joints from measured geometry:

```python
out[name] = {"x": v[0], "y": v[2], "z": -v[1]}   # Blender Z-up -> glTF Y-up
```

- In the picker, convert the raycast hit with `model.worldToLocal(point)` and store
  that. **Do not re-centre the model in the picker page** — the room re-centres it to
  sit on the floor, and only `worldToLocal` makes the two agree.
- Scale the joints by the same factor you scale the mesh by; otherwise legs placed
  from a 1 m reconstruction land outside a 2 m rig.

## Picking UX that works

16 joints: `neck`, `head`, `spine`, `hips` plus `hip`/`knee`/`hoof` per leg
(`FL`, `FR`, `BL`, `BR`). Requirements learned from use:

- Click a joint in the list to arm it, then click the model surface; **auto-advance**
  to the next unset joint so a full pass is 16 clicks with no list interaction.
- Distinguish a click from an orbit drag (`< 4 px` movement) or the camera fight
  with the picker.
- Concrete save feedback naming the asset and count, plus a build log streamed into
  the page — the build takes ~1 min and silence reads as a hang.
- **Seed the joint file from measured geometry before handing it over**
  (`scratch/seed_joints.py`). Opening a picker with 16 empty slots invites the user
  to do work the machine already did; pre-placed joints become nudges instead.

## Build step

`scratch/rig_from_joints.py <src.glb> <dst.glb> <joints.json> [--scale-to N]`:

1. Import, keep the largest mesh, drop stray helper meshes.
2. Scale mesh and joints together to the target real-world length.
3. Build the armature from the picked points: `root`→`spine`→`neck`→`head`, plus
   upper/lower per leg, front legs parented to `spine`, rear to `root`.
4. Weight **island-rigid** (see `references/blender-authoring.md`) — per-vertex
   weighting smears on this mesh family.
5. Gate leg capture: below each hip joint, inside a radius fitted from the picked
   chain, and nothing forward of the front legs.
6. Trot cycle, then export with `export_skins=True`.

## Pitfalls

- **Relative paths in the build endpoint resolve against the stack root, not the
  panel's cwd.** Resolve `Path(p)` against `~/media-stack` when it is not absolute,
  or the build fails with a missing input.
- An empty bone produces a limb that cannot deform at all. After island binding,
  hand any unweighted bone its **nearest whole island** — doing this before the
  island pass is pointless, since that pass can empty a group again.
- Watched task state: the panel runs Blender with `start_new_session=True` and
  writes `rig/build_<asset>.log`; the page polls `build/status` and looks for
  `wrote` / `done:` / `Traceback` to decide it finished.
