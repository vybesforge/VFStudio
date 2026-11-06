---
name: studio-animation
description: "Use when rigging, animating or making sprite sheets."
version: 1.0.0
author: Jimmy
license: Apache-2.0
platforms: [macos, linux]
metadata:
  hermes:
    category: studio
    tags: [studio, animation, blender, rigify, grease-pencil, spritesheet, krita, tahoma2d, opentoonz, gltf, godot]
---

# studio-animation — rig, animate, sprite-sheet (all local)

> **Save deliverables under `~/media-stack/output/3d/ for rigged GLBs, output/video/ for renders, output/image/ for sprite sheets`** — that is where the VF Studio panel (http://127.0.0.1:8787) looks; files elsewhere never show up or preview there. Any subfolder inside is fine.

Blender 5.2 headless scripts for 3D auto-rigging (Rigify) with a baked test cycle and glTF export,
Grease Pencil 2D animation rendered to PNG + mp4, PNG-sequence → VSE mp4, a sprite-sheet /
Godot `SpriteFrames` builder (with chroma keying for AI-generated sprites), and the hand-drawn path
through Krita and Tahoma2D/OpenToonz. Outputs drop straight into the `studio-game` templates.

## When to Use
- "Rig this GLB/OBJ/FBX and make it move" → Recipe 1 (+ Recipe 2 to prove it deforms).
- "Make a 2D animation / bouncing ball / growing line in Blender" → Recipe 3.
- "Turn these PNG frames into a sprite sheet for Godot" → Recipe 4; AI sprites → Recipe 5.
- "I drew frames in Krita — get them into Blender / Godot / a video" → Recipes 6-7.
- "Open a hand-drawn animation app" → Recipe 8 (Tahoma2D works; OpenToonz needs Rosetta).
- Not for: video editing of finished clips (`studio-video-edit`), VR optimisation (`studio-vr`), a falling prop or soft-body shot (`studio-physics`).

## Prerequisites (exact paths — verify, don't reinstall)
| Thing | Path |
|---|---|
| Blender 5.2.3 (ALWAYS via wrapper) | `~/media-stack/bin/blender` (`-b --python script.py -- args`); absolute paths only |
| Python venv (pillow, numpy) | `~/media-stack/tools/.venv/bin/python` |
| ffmpeg | `~/.hermes/tools/ffmpeg-9.0.1-darwin-arm64/ffmpeg` (no ffprobe; count frames with `ffmpeg -i f.mp4 -map 0:v -f null -`) |
| Auto-rig | `~/media-stack/tools/anim/rigify_auto.py` |
| Rig/anim verifier | `~/media-stack/tools/anim/verify_anim_glb.py` |
| Grease Pencil demo | `~/media-stack/tools/anim/gp_anim.py` |
| PNG sequence → VSE mp4 | `~/media-stack/tools/anim/pngseq_to_vse.py` |
| Sprite sheet + .tres | `~/media-stack/tools/anim/spritesheet.py`; placeholder frames: `~/media-stack/tools/anim/make_test_frames.py` |
| Local image gen (sprites) | `~/media-stack/tools/comfy/gen image "..." --model klein --w 1024 --h 1024` (ComfyUI must answer `curl -s 127.0.0.1:8188/system_stats`) |
| Krita 5 | `/Applications/Krita.app` (GUI; animation export is GUI-only) |
| Tahoma2D 1.6.3 (arm64, OpenToonz fork) | `/Applications/Tahoma2D.app` (+ CLIs `Contents/MacOS/tcomposer`, `tconverter`) |
| OpenToonz 1.8.0 (x86_64 — needs Rosetta, see Pitfalls) | `/Applications/OpenToonz.app`, stuff in `/Applications/OpenToonz/OpenToonz_stuff` |
| Test meshes (read-only) | `~/media-stack/vr/pig.glb` (actually a T-posed **human**, 1.2 M tris), `~/media-stack/scratch/pig_anim_test.glb` (a real quadruped, 94k tris) |
| Scratch | `~/media-stack/scratch/game-test/` |

Verify: `~/media-stack/bin/blender -b --version | head -1 && ls ~/media-stack/tools/anim/` → `Blender 5.2.3 LTS` and the five scripts.

## Recipes

### 1. Auto-rig a mesh with Rigify + bake a test cycle + export GLB
Intent: any static character mesh → skinned GLB with an "AutoCycle" animation Godot can play.
```bash
B=~/media-stack/bin/blender; A=~/media-stack/tools/anim; O=~/media-stack/scratch/game-test
# human (biped) — decimate heavy reconstructions to ~100k tris first
$B -b --python $A/rigify_auto.py -- --in ~/media-stack/vr/pig.glb --out $O/pig_human_rig.glb --decimate 100000 2>&1 | grep rigify_auto
# quadruped (Rigify "Basic Quadruped" metarig); body length is auto-rotated onto Y
$B -b --python $A/rigify_auto.py -- --in ~/media-stack/scratch/pig_anim_test.glb --out $O/hog_quad_rig.glb --quadruped 2>&1 | grep rigify_auto
```
Expected (human run, 26 s wall):
```
[rigify_auto] imported pig.glb: 1199722 faces, 674961 verts, merged 1 mesh(es)
[rigify_auto] decimated ratio=0.083 -> 99999 faces (10.2s)
[rigify_auto] metarig human scaled by (0.58, 0.65, 0.51)
[rigify_auto] rigify generated: 706 bones, 160 deform (13.0s)
[rigify_auto] AUTO (bone heat) coverage 0.0% < 98% -> trying ENVELOPE
[rigify_auto] weights=ENVELOPE coverage=100.0% (16.7s)
[rigify_auto] animation 'AutoCycle' 24 frames @ 24 fps, 18 fcurves, bones=['foot_ik.L', 'foot_ik.R', 'hand_ik.L', 'hand_ik.R', 'torso', 'head']
[rigify_auto] wrote .../pig_human_rig.glb (36.8 MB) in 22.9s
```
The quadruped run on `pig_anim_test.glb` goes one step further: `ENVELOPE coverage 51.3% < 98% -> PROXIMITY (nearest deform bone)` then `weights=PROXIMITY coverage=100.0%`. The `weights=` line tells you which binding won — report it to the user: AUTO = proper bone heat, ENVELOPE/PROXIMITY = coarse (fine for a test cycle, not for hero animation).
Options: `--frames 24 --fps 24` cycle length, `--uniform` (fit by height only instead of per-axis bbox fit), `--flip` (model faces +Y), `--length-axis x|y`, `--no-anim`, `--save-blend /abs/rig.blend` (open in the Blender GUI to refine weights/poses; all Rigify controls are there, only DEF bones are exported).
Supported inputs: `.glb .gltf .fbx .obj`. Existing armatures/animations in the input are stripped.

### 1b. Key a locomotion clip onto an already-rigged GLB (walk / trot / gallop / idle)
Intent: the rig exists (panel **Build rig**, or `rigify_auto.py`) and you want a named, looping clip on it.
```bash
stack anim vr/hog_trellis2_rigged.glb --clip walk --frames 24      # or: --clip trot|gallop|idle
# equivalently: bin/blender -b --python tools/anim/animate_clip.py -- <in.glb> <out.glb> --clip trot
```
Writes `<in>_anim.glb`, or `vr/<asset>_anim.glb` from the panel's **3D tab → Animate the built rig** card (`POST /api/rig/animate`, clip + frames). The room's **Anim** button plays clip 0 by name; `verify_anim_glb.py` proves it moves (`max_disp > 0`, `moving_frac`).
Clips are procedural sine gaits, not a motion model: upper limb swings at cycle rate, lower lags 0.12 of a cycle at 55% amplitude, body pitches at twice the stride rate, head counter-rotates. Gait phases are a `GAITS` table — lateral-sequence walk (BL 0, FL .25, BR .5, FR .75), trot (diagonal pairs), gallop (front pair then back pair, 1.5x amplitude).
Bone naming handled: `FL_upper/FL_lower…` (rig_from_joints.py) and Rigify `DEF-thigh.L` / `DEF-front_thigh.L` / `DEF-upper_arm.L` (strip `DEF-`, skip the `.001` secondary deform twins — animating them with their parent doubles the rotation).
Gotchas: a mesh with a baked base/plinth gets the plate weighted too, so the ground warps as the animal walks — animate a clean mesh; and `stack` runs with `set -u`, so loop variables need initialising.

### 2. Prove the GLB is skinned and actually moves (no rendering)
```bash
~/media-stack/bin/blender -b --python ~/media-stack/tools/anim/verify_anim_glb.py -- ~/media-stack/scratch/game-test/pig_human_rig.glb 2>&1 | grep '^{'; echo exit=$?
```
Expected:
```
{"ok": true, "file": ".../pig_human_rig.glb", "skinned": true, "bones": 160, "actions": ["AutoCycle"], "frames": [1, 24], "tris": 100079, "verts": 96371, "max_disp": 0.04298, "mean_disp": 0.01991, "moving_frac": 1.0}
exit=0
```
Numbers measured on this machine: human rig `max_disp=0.043 m` on a 1.0 m tall mesh; quadruped on the same mesh `0.063`; real quadruped `hog_quad_rig.glb` `max_disp=0.303, mean 0.075` (2 m long). `ok=false`/exit 1 means no skin, no action, or nothing moves (max_disp ≤ 1e-4) — do not hand such a file to Godot. Displacement is read through the depsgraph (`evaluated_get` at 5 frames), so it reflects what any glTF player will show.
Then play it in a game: `/Applications/Godot.app/Contents/MacOS/Godot --headless --path ~/media-stack/game/templates/godot-3d --quit-after 5 -- /abs/file.glb 2>&1 | grep -E "ANIM_|GLB_LOAD"` → `ANIM_PLAY AutoCycle (1 clips)` (see `studio-game`).

### 3. Grease Pencil 2D animation → PNG sequence + mp4
```bash
~/media-stack/bin/blender -b --python ~/media-stack/tools/anim/gp_anim.py -- --out ~/media-stack/scratch/game-test/gp_ball --mode ball --frames 48 --fps 24 --res 1280x720 2>&1 | grep -E "gp_anim|^\{"
```
Expected (5 s):
```
[gp_anim] drew 48 GP frames, mode=ball, 3 materials
[gp_anim] rendered 48 PNGs to .../gp_ball/frames
[gp_anim] wrote .../gp_ball/gp_anim.mp4 (0.11 MB)
{"ok": true, "frames": 48, "png_dir": ".../gp_ball/frames", "mp4": ".../gp_ball/gp_anim.mp4", "res": [1280, 720]}
```
`--mode line` = growing wiggling line. `--save-blend /abs/f.blend` keeps the GP object to continue drawing in the GUI. To draw your own shapes, copy `add_stroke(drawing, [(x, z), ...], radius, material, cyclic)` — the Blender 5 GP API in one place: `bpy.data.grease_pencils.new()`, `gp.layers.new()`, `layer.frames.new(frame)`, `frame.drawing.add_strokes([n_points])`, `stroke.points[i].position/radius/opacity`, `stroke.fill_opacity = 1.0`. Check a frame with `vision_analyze` before reporting.

### 4. Sprite sheet + Godot SpriteFrames from PNG frames
Intent: `dir/idle_000.png … run_005.png` → one sheet + `.tres` the 2D template's AnimatedSprite2D uses directly.
```bash
PY=~/media-stack/tools/.venv/bin/python; A=~/media-stack/tools/anim; O=~/media-stack/scratch/game-test
$PY $A/make_test_frames.py $O/frames --size 64 --idle 4 --run 6            # placeholder frames (skip if you have art)
$PY $A/spritesheet.py $O/frames --anim idle --anim run --fps 8 --trim --frame-size 64x64 \
    --out $O/player_sheet.png --tres $O/player_frames.tres --res-path res://player/player_sheet.png
```
Expected: `{"ok": true, "sheet": ".../player_sheet.png", "size": [384, 128], "frame": [64, 64], "cols": 6, "rows": 2, "animations": {"idle": 4, "run": 6}, "tres": ".../player_frames.tres", "res_path": "res://player/player_sheet.png"}`.
Layout: each `--anim` starts a new row; frames are bottom-aligned, centred, NEAREST-scaled (use `--smooth` for painted art). `--trim` crops to the union alpha bbox of all frames so the pivot stays stable. `--res-path` must be where the PNG will live inside the Godot project. Copy both files into `<project>/player/` and run `Godot --headless --path <project> --import`. Without `--anim`, all PNGs in the dir become one animation named `--name` (default `default`).

### 5. AI-generated sprite frames (local ComfyUI) keyed to transparency
```bash
curl -s 127.0.0.1:8188/system_stats >/dev/null || echo "ComfyUI down: stack start comfy"
O=~/media-stack/scratch/game-test; mkdir -p $O/gen_frames
~/media-stack/tools/comfy/gen image "pixel art game sprite of a small knight character standing idle, full body, centered, side view, flat solid bright magenta background, no shadow, clean edges" --model klein --w 1024 --h 1024
cp ~/media-stack/output/image/klein_0000N_.png $O/gen_frames/knight_000.png       # path from the JSON line gen printed
~/media-stack/tools/.venv/bin/python ~/media-stack/tools/anim/spritesheet.py $O/gen_frames --anim knight --key auto --trim --frame-size 128x128 --out $O/knight_sheet.png --tres $O/knight_frames.tres --res-path res://knight_sheet.png
```
Expected: gen takes ~37 s; sheet JSON `"size": [128, 128]`; alpha histogram is bimodal (measured: 11543 px fully transparent, 4815 opaque, 26 in between). `--key auto` keys the median border colour (AI backgrounds are never perfectly flat — a single corner pixel is not enough); `--key ff00ff --key-tol 80` to force a colour. Generate each pose as its own image with the same prompt + "frame 2 of a walk cycle, left foot forward" etc.; consistency across frames is the weak spot of text-to-image — expect to pick the best of `--n 4`.

### 6. Krita hand-drawn animation → PNG sequence → Blender VSE mp4 / Godot
Krita (GUI, no CLI for animation): draw on the Animation timeline → **File ▸ Render Animation…** → *Image Sequence*, Base name `frame`, Format PNG, Start/End = your range, Directory e.g. `~/media-stack/scratch/game-test/krita_out` → files `frame0000.png, frame0001.png, …`. (Krita can also write a video directly if Settings ▸ Configure Krita ▸ General ▸ *FFmpeg location* = `~/.hermes/tools/ffmpeg-9.0.1-darwin-arm64/ffmpeg`.)
Then:
```bash
B=~/media-stack/bin/blender; A=~/media-stack/tools/anim; D=~/media-stack/scratch/game-test/krita_out
# mp4 through the Blender VSE (one image-sequence strip; --hold 2 = "on twos"; --bg for transparent PNGs)
$B -b --python $A/pngseq_to_vse.py -- --frames $D --out $D/krita.mp4 --fps 24 --hold 2 --bg 1,1,1 2>&1 | grep -E "pngseq|^\{"
# Godot sprite animation
~/media-stack/tools/.venv/bin/python $A/spritesheet.py $D --name walk --fps 12 --trim --frame-size 128x128 --out $D/walk_sheet.png --tres $D/walk_frames.tres --res-path res://walk_sheet.png
```
Expected (tested with the gp_line frames): `[pngseq] 24 PNGs 640x360 -> 48 frames @ 24 fps` then `{"ok": true, "frames": 48, ...}`. Into a Blender **Grease Pencil** scene: open the GUI (`~/media-stack/bin/blender`), *Add ▸ Image ▸ Reference* (pick the first PNG, tick *Sequence*) as a rotoscope layer under your GP object, or *Object ▸ Trace Image to Grease Pencil* to vectorise the frames — both are editor-only (see Pitfalls).

### 7. Tahoma2D / OpenToonz as the drawing app (import + export path)
- Launch: `open -a Tahoma2D` (arm64, verified it starts). Frames from Krita/`gp_anim.py` load with **Level ▸ Load Level…** if named `name.0001.png` (dot + 4 digits): `cd DIR && i=1; for f in frame_*.png; do cp "$f" "$(printf 'ball.%04d.png' $i)"; i=$((i+1)); done`.
- Export: **Render ▸ Output Settings…** → format `png` (sequence) or `mp4` (Preferences ▸ Import/Export ▸ FFmpeg path = the ffmpeg above). Then Recipe 4/6 for Godot or video.
- Headless render of a saved scene: `/Applications/Tahoma2D.app/Contents/MacOS/tcomposer /abs/scene.tnz -o /abs/out.png -range 1 48` (first set `export TAHOMA2DROOT=/Applications/Tahoma2D.app/Contents/Resources/tahomastuff`).
- OpenToonz 1.8.0 is installed at `/Applications/OpenToonz.app` but is an **x86_64 binary**; this Mac has no Rosetta (`arch -x86_64 /usr/bin/true` → "Bad CPU type"). Installing Rosetta needs an admin: `softwareupdate --install-rosetta --agree-to-license`. Until then use Tahoma2D (same lineage, same `.tnz` scenes, same Load Level/Output Settings menus).

## Verify
```bash
B=~/media-stack/bin/blender; A=~/media-stack/tools/anim; O=~/media-stack/scratch/game-test
$B -b --python $A/rigify_auto.py -- --in ~/media-stack/scratch/pig_anim_test.glb --out $O/_v.glb --quadruped --frames 12 >/dev/null 2>&1 && \
$B -b --python $A/verify_anim_glb.py -- $O/_v.glb 2>&1 | grep -q '"ok": true' && \
$B -b --python $A/gp_anim.py -- --out $O/_gp --frames 6 --res 320x180 2>&1 | grep -q '"ok": true' && \
~/media-stack/tools/.venv/bin/python $A/make_test_frames.py $O/_fr >/dev/null && ~/media-stack/tools/.venv/bin/python $A/spritesheet.py $O/_fr --anim idle --anim run --out $O/_s.png --tres $O/_s.tres | grep -q '"ok": true' && echo ANIM_TOOLKIT_OK
```
Expected last line: `ANIM_TOOLKIT_OK` (≈ 15 s).

## Pitfalls (hit while building this)
- **Bone heat fails on reconstructed meshes** (`Warning: Bone Heat Weighting: failed to find solution for one or more bones`) and leaves *every* vertex unweighted while `parent_set` still returns FINISHED — always measure coverage, never trust the return value. `rigify_auto.py` falls back to ENVELOPE then PROXIMITY for that reason.
- **glTF import sets `rotation_mode = 'QUATERNION'`**; writing `obj.rotation_euler` then does nothing (the first quadruped run "rotated" the mesh and the bbox did not change). Set `rotation_mode = "XYZ"` first.
- **`obj.bound_box` is stale right after `transform_apply`** — compute bboxes from vertices (numpy `foreach_get("co")`), or call `view_layer.update()`.
- **Blender 5.x API renames**: `bpy.data.grease_pencils` (not `grease_pencils_v3`), `scene.sequence_editor.strips` (not `.sequences`), `strips.new_effect(..., length=N)` (no `frame_end`), slotted actions expose curves via `action.layers[].strips[].channelbags[].fcurves` (no `action.fcurves`), `MaterialGPencilStyle.show_fill/show_stroke` are deprecated (fill is on when `fill_color` alpha > 0).
- **GP strokes created with `add_strokes()` have `fill_opacity = 0`** → material fill invisible until you set it to 1.0 per stroke.
- **The GLB importer leaves the scene range at 1-250**; read the action's `frame_range` before sampling, or the "end" frame is just the last pose held.
- **`grease_pencil.trace_image` does nothing in `-b` mode** (operator finishes, layer stays empty) — tracing PNGs into GP strokes is a GUI job; headless, composite PNG sequences in the VSE instead.
- `pig.glb` is a human T-pose despite the name; `--quadruped` on it still "works" (bbox fit) but the rig is nonsense — pick the metarig by looking at the mesh (`vision_analyze` a Workbench render) not by filename.
- OpenToonz brew cask is disabled and the 1.8.0 release is x86_64-only `.pkg` (`pkgutil --expand-full` + copy `Payload/Applications/OpenToonz.app` works without sudo; the stuff folder comes from `Scripts/stuff.tar.bz2` → `/Applications/OpenToonz/OpenToonz_stuff`). Tahoma2D ships an arm64 portable dmg.
- The ComfyUI venv is not on PATH for `spritesheet.py`; run it with `~/media-stack/tools/.venv/bin/python` (a leaked `PYTHONPATH` from another venv breaks PIL's `_imaging` import).
