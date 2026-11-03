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
  `GET|POST /api/rig/joints`, `POST /api/rig/build`, `GET /api/rig/build/status`,
  `POST /api/rig/auto` + `/api/rig/auto/status` (VLM pre-placement),
  `POST /api/rig/animate` + `/api/rig/animate/status` (locomotion clip),
  `GET /api/vr/current` (which GLB the room opens).
- **Store joints per asset** (`rig/joints_<slug>.json`), not in one shared file, so
  a new project starts from a clean slate instead of inheriting the previous
  animal's anatomy — and make the slug come from the **file that was actually
  loaded**, or the per-asset storage silently does the wrong thing (next section).

## Asset identity — the loaded filename IS the asset key

The picker names its joint set after the asset the room loaded, so anything that
renames assets on the way in breaks the association. `set in room` used to copy
every GLB to `vr/pig.glb`; loading a human then made the room open asset `pig` and
the picker helpfully loaded **the hog's joints**, while the original `vr/pig.glb`
was destroyed by the copy. Rules:

- Copy to `vr/<own-file-name>.glb` and record the choice in `vr/current.json`; the
  room asks `GET /api/vr/current` when no `?src=` is given.
- Keep a per-asset joint file keyed on that same slug, and show the pairing
  (`asset → joints_<slug>.json`) in the panel so a mismatch is visible before the
  user clicks 16 joints into the wrong set.
- Derive the slug in the page from the URL/filename (`?asset=` wins, else the
  `src` basename), never from a hardcoded default.
- If an asset got clobbered this way, the original is usually still in the
  generator's output tree — check `ComfyUI/output/3d/` by byte size and tri count
  before declaring it lost.

## Pre-place, then centre: the two automatic passes

Hand-placing 16 joints is the reliable path but a slow first draft. Two tools sit
between "empty" and "hand-picked", and both are CLI + panel driven
(`stack rig auto …`, the room's **AI auto-place** button):

1. **`tools/rig/auto_joints.py`** (+ `render_views.py`) — Blender workbench renders
   ±X/±Y orthographic views at 1024 px plus a manifest whose pixel↔world map is
   measured with `world_to_camera_view`; the local VLM classifies the asset
   (biped/quadruped), picks the face-on or profile view, and names each landmark as
   a **cell on a 20×20 labelled grid**; each guess is then snapped into the mesh
   (thin vertex slab, clustered across the limb or depth axis, medianed for depth),
   followed by one review pass on the labelled overlay.
   - **Ask for grid cells, never coordinates.** The same model answers "percent",
     "0-1000 grid" and "pixels", and mixes them inside one reply (hips `[50,488]`);
     cell names are unambiguous and 20×20 at 1024 px is the resolution that made it
     land on anatomy (~2.5% of body span) where 10×10 was ~10% out.
   - Crop to the silhouette and pad to a **square** before sending: a 688×392 render
     is read as square and every joint comes back too low.
   - `render_views.py` must use `to_track_quat('-Z','Y')` for every camera; passing
     the track axis as the up axis (`'Z'`) makes Blender pick a random roll and the
     rear view arrives upside down, which the VLM then reasons about.
2. **`tools/rig/center_joints.py`** — hand-picked joints are surface picks (0.2–1.1 mm
   from the skin), so bones run along the front of the body. This casts inward from
   the nearest surface point (own triangle normal, then the depth axis, then flipped),
   takes the midpoint of the first solid run, refuses midline drift, and only keeps
   points `mesh.contains()` confirms. Measured on a human: every joint went to
   7.6–59.3 mm inside with mirrored pairs intact. `--factor 0.5` goes half way and
   `--only <joint>` re-does one joint after a nudge; `--write` backs up to
   `rig/attic/` first.
   - **`mesh.contains`/`ray` need `rtree` in the tools venv** (trimesh imports it
     lazily; without it the failure is `No module named 'rtree'` mid-run).
   - **An asset with a baked plinth cannot be centred.** A rigged export arrived
     with 99% of its vertices in a 1.95 × 1.95 m ground plate; centring snapped every
     joint into the plate and the moves were 200–480 mm. Check the bottom-slab vertex
     share before trusting a centring result, and prefer the clean mesh.
3. **`tools/rig/inspect_joints.py`** — the QA gate: per-joint distance to the surface
   and height fraction, flags spine-order violations (bipeds only — a quadruped's
   head is legitimately lower than its back), unmirrored pairs and points off the
   mesh, and writes `check_front.png` / `check_side.png`. Run it after every save and
   after every centring pass instead of re-reading the JSON by eye.

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
6. Trot cycle, then export with `export_skins=True`. For anything other than the
   built-in cycle use `tools/anim/animate_clip.py` (`stack anim <glb> --clip
   walk|trot|gallop|idle`) — it keys one named clip on either a hand-built
   `FL_upper/FL_lower` chain or Rigify's `DEF-thigh.L` / `DEF-front_thigh.L` /
   `DEF-upper_arm.L` names (strip `DEF-`, skip the `.001` twins or the rotation
   doubles). See the `studio-animation` skill.

## Pitfalls

- **Bookkeeping keys break the builder.** The picker saves `_template`, `_source`,
  `_src` beside the joints; a builder that iterates every value as a point dies with
  `TypeError: string indices must be integers` **after** the import, so Build rig
  fails on every set the picker wrote. Skip keys starting with `_` and entries that
  are not `{x,y,z}` dicts, and read the build log rather than assuming success.
- **A skinned asset must be picked on its bind pose.** With an animation clip
  playing, the mesh bobs under the cursor and the click lands on a moving surface
  while the coordinates are stored against the rest pose. Pause and rewind the clip
  when rig mode opens (the room's Anim button, `mixer.timeScale = 0` + `setTime(0)`).
- **Relative paths in the build endpoint resolve against the stack root, not the
  panel's cwd.** Resolve `Path(p)` against `~/media-stack` when it is not absolute,
  or the build fails with a missing input.
- An empty bone produces a limb that cannot deform at all. After island binding,
  hand any unweighted bone its **nearest whole island** — doing this before the
  island pass is pointless, since that pass can empty a group again.
- Watched task state: the panel runs Blender with `start_new_session=True` and
  writes `rig/build_<asset>.log`; the page polls `build/status` and looks for
  `wrote` / `done:` / `Traceback` to decide it finished.
