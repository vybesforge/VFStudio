---
name: studio-game
description: "Use when building a Godot 4 2D/3D game or exporting it."
version: 1.0.0
author: Jimmy
license: MIT
platforms: [macos]
metadata:
  hermes:
    category: studio
    tags: [studio, godot, game, 2d, 3d, export, glb, spritesheet, headless]
---

# studio-game — Godot 4.7 game toolkit (local, headless-checkable)

> **Save deliverables under `~/media-stack/game/<project>/ (the panel lists it; web builds get a Play button)`** — that is where the VF Studio panel (http://127.0.0.1:8787) looks; files elsewhere never show up or preview there. Any subfolder inside is fine.

Two ready Godot 4.7.2 templates (2D platformer, 3D first/third-person), a script that stamps a new
project from them, and the exact commands to run, self-test, import GLBs / sprite sheets, and export
macOS + Windows builds without opening the editor. Everything runs on this Mac; nothing phones home.
For making the *assets* (sprite sheets, rigged GLBs, 2D animation) load `studio-animation`.

## Where projects live (so the VF Studio panel sees them)
Put every game under **`~/media-stack/game/<name>/`** (Godot: has `project.godot`; web: has `package.json` or `index.html`). The panel's *3D & VR → Game projects* card lists them automatically and merges their GLB/audio/sprite files into the galleries. For a web game run the production build (`npm run build` → `dist/index.html`) — the panel serves it at `http://127.0.0.1:8787/files/game/<name>/dist/index.html` behind a **▶ Play in browser** button. Projects elsewhere on disk are invisible to the panel.

## When to Use
- "Make me a 2D platformer / 3D walking sim / game prototype" → Recipe 1, then edit scripts.
- "Put this GLB / character in a game and play its animation" → Recipe 3 (3D template loads any GLB).
- "Export the game for Windows / macOS" → Recipe 4.
- "Does this Godot project still run?" → Recipe 5 (headless checks, zero-error gate).
- Not for VR (use `studio-vr`), not for authoring meshes or rigs (use `studio-animation`).

## Prerequisites (all installed — verify, don't install)
| Thing | Exact path |
|---|---|
| Godot 4.7.2 (editor + headless runner) | `/Applications/Godot.app/Contents/MacOS/Godot` |
| Export templates 4.7.2 | `~/Library/Application Support/Godot/export_templates/4.7.2.stable/` (`macos.zip`, `windows_release_x86_64.exe`) |
| 2D template | `~/media-stack/game/templates/godot-2d/` — CharacterBody2D + AnimatedSprite2D (idle/run from `player/player_sheet.png` + `player/player_frames.tres`), TileMapLayer floor built in code, Camera2D follow, 3 coins (Area2D), HUD label, `export_presets.cfg` (macOS + Windows Desktop) |
| 3D template | `~/media-stack/game/templates/godot-3d/` — CharacterBody3D (WASD, mouse look, Space, V toggles 1st/3rd person), floor StaticBody3D, sun + fill light, loads a GLB from the path after `--` and plays its first AnimationPlayer clip |
| Project stamper | `~/media-stack/game/new_project.sh <2d\|3d> <Name> <dest>` |
| Sprite sheet / SpriteFrames builder | `~/media-stack/tools/anim/spritesheet.py` (see `studio-animation`) |
| Test GLBs | `~/media-stack/vr/pig.glb` (read-only; NOTE: despite the name it is a T-posed human, 1.2 M tris, no animation), `~/media-stack/scratch/game-test/pig_human_rig.glb` (rigged + "AutoCycle" clip) |
| Scratch | `~/media-stack/scratch/game-test/` |

Verify in one shot:
```bash
/Applications/Godot.app/Contents/MacOS/Godot --headless --version && ls ~/media-stack/game/templates/ && ls "$HOME/Library/Application Support/Godot/export_templates/4.7.2.stable/" | grep -c -E "macos.zip|windows_release_x86_64.exe"
```
Expected: `4.7.2.stable.official.ed1daf0bf`, `godot-2d godot-3d`, `2`.

## Recipes

### 1. New project from a template
Intent: copy a template, rename it, get the run/export commands printed.
```bash
~/media-stack/game/new_project.sh 2d MyPlatformer ~/media-stack/scratch/game-test/MyPlatformer
```
Expected (first lines): `created 2d project "MyPlatformer" at /Users/dcruse/media-stack/scratch/game-test/MyPlatformer` followed by the exact run/editor/export commands. Use `3d` for the 3D template. Destination must not exist yet. `build/` and `.godot/` are not copied; the script runs `--import` once so the first run is clean.

### 2. Run a project (headless check, window, editor)
```bash
G=/Applications/Godot.app/Contents/MacOS/Godot
P=~/media-stack/game/templates/godot-2d          # or any project dir
$G --headless --path $P --quit-after 5 2>&1 | grep -vE "^$|Godot Engine"   # no window, prints and quits
$G --path $P                                                                # play with a window
$G --editor --path $P                                                       # open the editor
```
Expected 2D template output (exactly these two lines, no `ERROR`/`SCRIPT ERROR`):
```
2D_READY tiles=139 coins=3 player=(64.0, 192.0)
2D_FRAME on_floor=true pos=(64.0, 192.0)
```
2D self-test (walks right into a coin, exits 0 on success):
```bash
$G --headless --path ~/media-stack/game/templates/godot-2d -- --selftest 2>&1 | grep 2D_; echo exit=$?
```
Expected: `... 2D_COIN total=1` then `2D_SELFTEST OK frames=39 coins=1`, `exit=0`.

### 3. 3D template: load any GLB and play its first animation
Intent: see a GLB standing on the floor 4 m in front of the player, animated if it has a clip.
```bash
G=/Applications/Godot.app/Contents/MacOS/Godot
$G --headless --path ~/media-stack/game/templates/godot-3d --quit-after 40 -- /ABS/PATH/model.glb 2>&1 | grep -E "GLB_|ANIM_|3D_FRAME|ERROR"
```
Expected (rigged test file `~/media-stack/scratch/game-test/pig_human_rig.glb`):
```
GLB_INFO size_m=1.63x1.80x0.34 scale=1.799 tris=99999
ANIM_PLAY AutoCycle (1 clips)
GLB_LOAD OK /Users/dcruse/media-stack/scratch/game-test/pig_human_rig.glb
3D_FRAME on_floor=true pos=(0.0, 0.000043, 2.0)
```
A static GLB prints `ANIM_NONE` instead. No path after `--` → defaults to `~/media-stack/vr/pig.glb`. Drop `--headless` to play it. The loader is `main.gd: load_glb()` (GLTFDocument → generate_scene → fit to 1.8 m → `_play_first_animation`); copy that function into any project that must load models at runtime. For GLBs that ship *inside* the project instead, put the .glb under the project dir, run `$G --headless --path $P --import`, then `preload("res://model.glb").instantiate()`.
Heavy GLBs (>200k tris, 4K textures): shrink first with `~/media-stack/tools/vr/optimize_glb.sh in.glb out.glb --target-tris 100000 --tex 2048` (see `studio-vr`). Godot cannot import meshopt/Draco-compressed GLBs.

### 4. Export macOS + Windows builds (headless)
```bash
G=/Applications/Godot.app/Contents/MacOS/Godot; P=/ABS/project/dir; NAME=Game
mkdir -p $P/build
$G --headless --path $P --export-release "Windows Desktop" $P/build/$NAME.exe   > $P/build/export_win.log 2>&1; echo win_exit=$? errors=$(grep -c ERROR $P/build/export_win.log)
$G --headless --path $P --export-release "macOS"           $P/build/$NAME-macos.zip > $P/build/export_mac.log 2>&1; echo mac_exit=$? errors=$(grep -c ERROR $P/build/export_mac.log)
ls -la $P/build/
```
Expected: `win_exit=0 errors=0`, `mac_exit=0 errors=0`; `Game.exe` ≈ 109 MB (`file` → `PE32+ executable (GUI) x86-64`, pck embedded), `Game-macos.zip` ≈ 60 MB (universal .app, ad-hoc signed, not notarized → first launch needs right-click → Open). Preset names are exactly `"Windows Desktop"` and `"macOS"` (from `export_presets.cfg`). Test the mac build: `unzip -qo build/Game-macos.zip -d build/mac && "build/mac/<Name>.app/Contents/MacOS/<Name>"`.

### 5. Headless zero-error gate (use after every edit)
```bash
G=/Applications/Godot.app/Contents/MacOS/Godot; P=/ABS/project/dir
$G --headless --path $P --import > /dev/null 2>&1
OUT=$($G --headless --path $P --quit-after 5 2>&1); echo "$OUT" | grep -E "ERROR|SCRIPT ERROR|WARNING" ; echo "$OUT" | grep -qE "SCRIPT ERROR|^ERROR" && echo GATE_FAIL || echo GATE_OK
```
Expected: `GATE_OK` and no `SCRIPT ERROR` lines. A GDScript parse error looks like `SCRIPT ERROR: Parse Error: ... at: GDScript::reload (res://main.gd:93)` — fix the line it names.

### 6. Use a sprite sheet made by spritesheet.py in a 2D project
Intent: new character animations without touching the editor.
```bash
P=/ABS/project/dir
~/media-stack/tools/.venv/bin/python ~/media-stack/tools/anim/spritesheet.py /ABS/frames_dir --anim idle --anim run --fps 8 --trim --frame-size 64x64 \
  --out $P/player/player_sheet.png --tres $P/player/player_frames.tres --res-path res://player/player_sheet.png
/Applications/Godot.app/Contents/MacOS/Godot --headless --path $P --import >/dev/null 2>&1
```
`player.tscn` already points its AnimatedSprite2D at `res://player/player_frames.tres`; `player.gd` calls `sprite.play("run")`/`"idle"`, so keep those animation names (or edit the two `play(...)` calls). The `.tres` is a plain SpriteFrames with AtlasTexture regions — Godot needs no import step for it, only for the PNG. The project uses nearest filtering (`textures/canvas_textures/default_texture_filter=0`) so pixel art stays crisp.

### 7. Where to edit (template map)
| Want | File |
|---|---|
| 2D movement speed / jump | `player.gd` `SPEED`, `JUMP_VELOCITY` |
| 2D level layout | `main.gd` `_ready()` — `floor_layer.set_cell(Vector2i(x, y), 0, Vector2i(tile_x, 0))`; tiles are 16 px, source 0 = `tiles/tiles.png` (0,0 grass, 1,0 dirt) |
| Add a collectible | instance `coin.tscn` in `main.tscn` (it joins group `coins` and emits `collected`) |
| 3D movement / mouse | `player.gd` `SPEED`, `RUN_SPEED`, `MOUSE_SENS`; keys are bound in `_ready()` via `InputMap` (no project-settings editing) |
| 3D model placement | `main.gd` `TARGET_HEIGHT`, `MODEL_POS` |
| Window / renderer | `project.godot` (`[display]`, `[rendering]`) — keep `textures/vram_compression/import_etc2_astc=true` or the macOS export fails |

## Verify
```bash
G=/Applications/Godot.app/Contents/MacOS/Godot
$G --headless --path ~/media-stack/game/templates/godot-2d -- --selftest 2>&1 | grep -q "2D_SELFTEST OK" && \
$G --headless --path ~/media-stack/game/templates/godot-3d --quit-after 5 2>&1 | grep -q "GLB_LOAD OK" && echo GAME_TOOLKIT_OK
```
Expected last line: `GAME_TOOLKIT_OK`.

## Pitfalls (hit while building this)
- **`Cannot infer the type of "names"`** — `var x := ap.get_animation_list()` fails to parse in 4.7; write `var names: PackedStringArray = ap.get_animation_list()`. Typed `:=` needs a statically typed right side.
- **`CharacterBody2D` reports `on_floor=false` on frame 1-3 if it spawns even 1 px above the ground** — spawn exactly on the surface or check after ~30 physics frames (the 3D template checks on frame 30).
- **Hand-written `TileMapLayer` cells**: `tile_map_data` in a .tscn is a packed binary blob; do not hand-edit it. Build the level in code with `set_cell()` (as `main.gd` does) — it is also what an LLM can edit reliably.
- **Input actions**: adding `[input]` entries to `project.godot` by hand is error-prone (serialized InputEvent objects). Use the built-in `ui_left/ui_right/ui_accept` and add extra keys with `InputMap.action_add_event()` in `_ready()`.
- **First export after adding files** takes longer because it imports; run `--headless --import` first to keep export logs clean.
- **macOS export**: `Cannot export for universal or arm64 if ETC2 ASTC texture format is disabled` → keep `import_etc2_astc=true` in `[rendering]`.
- `pig.glb` is a *human* T-pose mesh (1.2 M tris, no skin, no animation) despite its name — use it as a static-load test only.
