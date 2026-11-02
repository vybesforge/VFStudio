# Rig joints — pick, seed with the local VLM, centre, verify

Everything here is about `rig/joints_<asset>.json`, the per-asset joint set the WebXR room
(`vr/index.html`) edits and `scratch/rig_from_joints.py` turns into an armature. Coordinates are
**glTF space (Y up)**, the space `worldToLocal` in the room writes; Blender Z-up files leave every
marker off the model.

## The loop that works

1. **Load the asset in the room** — `http://127.0.0.1:8787/vr/index.html?src=/vr/<file>.glb&asset=<slug>`
   (or the gallery's *rig* button). The **asset slug keys the joint file**, so read the name at the
top-left and the panel line `loaded N saved joints for <slug>` before touching anything.
2. **Open Rig, pick or AI-place**, `Save joints`. The save posts to
   `/api/rig/joints?asset=<slug>` — the slug is derived from the *loaded file name*, not from what you
   meant to work on. If a save "didn't land", list the files: `ls -lT rig/joints_*.json` and
   `curl -s http://127.0.0.1:8787/api/rig/assets | python3 -m json.tool`. A set saved from
   `hog_quad_rig.glb` while you were thinking of `hog_trellis2` lands as
   `joints_hog_quad_rig.json`.
3. **Centre the picks inside the body** (see below) — clicking in the room means clicking skin, so an
   uncentred set puts the bones on the front surface instead of through the limb.
4. **Verify** with `inspect_joints.py`, then look at `check_front.png` / `check_side.png`.
5. `Build rig` (quadruped) or hand the file to `tools/anim/rigify_auto.py` (biped).

## Seeding a set with the local VLM

```bash
stack rig auto <src.glb> [asset]          # or: tools/.venv/bin/python tools/rig/auto_joints.py <src.glb>
```

Pipeline: `render_views.py` (Blender workbench, 1024 px, ±X/±Y ortho + manifest measured with
`world_to_camera_view`) → VLM classifies biped/quadruped, picks face-on vs profile → one 20×20 **grid
cell** per landmark → mesh snap (vertex slab, clustered across the limb axis or depth axis) → one
labelled-overlay review pass → `rig/joints_<asset>.json` with `_template` / `_source`.

Flags: `--template biped|quadruped|auto`, `--offline` (bbox-proportion fallback), `--no-refine`
(skips the second VLM pass, halves the runtime). ~90 s per asset on this Mac.

Quality measured here: bipeds and quadrupeds land on the right anatomy within a couple of cm
(`_source: vlm`). It is a seed to review, not a finished rig.

## Moving surface picks inside the joint

```bash
tools/.venv/bin/python tools/rig/center_joints.py <src.glb> --asset <slug> [--only L_hip] [--factor 0..1] --write
```

Per joint: nearest surface point → its triangle's normal, then the depth axis, then the flipped
normal → midpoint of the first solid run, capped at 6 % of span → keep only points `mesh.contains`
confirms. `--factor 0.5` goes half way. `--only a,b` re-centres just those joints, which is what you
want after the user nudges one marker (`--write` backs the file up to `rig/attic/` first).

Pepper's 17 hand picks went from ≤1.1 mm to 7.6–59.3 mm inside; pairs stayed mirrored to a couple of cm.

### When centring drifts toward the midline

A ray that is nearly lateral on a hip or shoulder walks the joint inboard, and the asymmetry is
visible in the rig. Two fixes, in order:
- Mirror the solved twin: take the well-centred side, write `x = -x` for the pair, then confirm with
  `mesh.contains` and a surface-distance check before saving.
- If the user's click was the ambiguous one, ask them to re-click the marker and save, then re-run
  with `--only`. Do not silently "fix" their position — check the file mtime first and quote what is
  actually in it.

## Verifying a set

```bash
tools/.venv/bin/python tools/rig/inspect_joints.py <src.glb> --asset <slug>
```

Prints per-joint distance to the surface, height fraction, and flags: body joints out of order
(biped only — a quadruped's head is legitimately below the back), unmirrored pairs, points off the
mesh. Writes `check_front.png` / `check_side.png` into `scratch/rig-views/<asset>/` (it needs that
directory's `views.json`; render once with `render_views.py` if absent).

## Pitfalls that cost real time

- **Check what the GLB actually contains before trusting any mesh metric.** `hog_quad_rig.glb` is
  156 502 vertices of which **154 996 are a 1.95 × 1.95 m base plate** and only ~1 000 make the hog —
  centring snapped joints to the plate and reported 200–480 mm moves. One line answers it:
  `python -c "import numpy as np,trimesh; v=np.asarray(trimesh.load(P,force='mesh').vertices); lo=v[:,1].min(); s=v[v[:,1]<lo+0.03*np.ptp(v[:,1])]; print(len(s)/len(v))"`
  (ratio > 0.5 = a plinth or a floor, not the subject). Prefer the clean source asset, or drop the
  plate component before measuring.
- **Never pick joints on a playing animation.** A skinned asset bobs under the cursor, so the click
  lands somewhere else, and the coordinates are stored against the bind pose regardless. The room
  has an **Anim** button (disabled when the asset has no clip) and rig mode auto-pauses and rewinds
  to frame 0 — keep that behaviour; picking against a running `AutoCycle` is what "the asset is
  jumping, so it's not exact" means.
- **An unconstrained max-min clearance search is not a centring method**: without an inside test it
  escapes the mesh, and with one it walks to the largest cavity (the torso) and drags every hoof to
  the belly. Keep the ray-and-first-solid-run approach above.
- **Rotated exports break axis assumptions.** A rigged export can sit ~45° off in XZ; then "depth
  axis" and "lateral" mean nothing and ray-based centring misbehaves. Check the footprint (feet
  clusters along x/z) before blaming the solver.
- **`rtree` is required** by trimesh's `proximity.closest_point` / `ray.intersects_location` /
  `contains`. It is in `install.sh`'s tools-venv line; if a fresh rig install fails with
  `ModuleNotFoundError: No module named 'rtree'`, that is the fix.
- **Don't rebuild a joint set with the template select.** Changing `<select id="rigtpl">` clears the
  picker; the template is also written into the file as `_template`, so a saved quadruped set will
  reopen as quadruped only if it was saved after the template was right.
