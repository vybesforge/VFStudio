---
name: studio-vr
description: "Use when loading, optimizing or exporting 3D/GLB assets for VR: Godot 4 OpenXR room, Windows SteamVR build, gltf-transform, local WebXR room."
version: 1.0.0
author: Jimmy
license: MIT
platforms: [macos]
metadata:
  hermes:
    category: studio
    tags: [studio, vr, godot, openxr, gltf, glb, webxr, steamvr]
---

# studio-vr

Local-only VR / real-time 3D toolkit on the M3 Max: Godot 4.7.2 (OpenXR, Forward+) room that
loads any GLB at runtime, headless exports for macOS and Windows (SteamVR box), and a
gltf-transform pipeline that shrinks TRELLIS/ComfyUI GLBs to VR budgets. Nothing here fetches
from a CDN at runtime. No headset is attached to this Mac — VR is tested on the Windows RTX 4080
SteamVR machine; on the Mac everything runs in a desktop free-fly fallback.

## When to use
- "Put this GLB in the VR room" / "view model X in VR" → Recipe 1 (Godot) or Recipe 4 (WebXR).
- "Build the Windows VR app for the SteamVR PC" → Recipe 2.
- "This GLB is too heavy (700k+ tris, 4K textures)" → Recipe 3.
- Don't use for: authoring/animating meshes (use the `Blender` skill), image/video generation (ComfyUI).

## Prerequisites (all already installed — just verify)
| Thing | Exact path |
|---|---|
| Godot editor (4.7.2.stable, universal) | `/Applications/Godot.app/Contents/MacOS/Godot` |
| Export templates | `~/Library/Application Support/Godot/export_templates/4.7.2.stable/` (must contain `macos.zip`, `windows_release_x86_64.exe`, `version.txt`) |
| Godot OpenXR project | `~/media-stack/vr-godot/` (`project.godot`, `main.tscn`, `main.gd`, `desktop_camera.gd`, `grid.gdshader`, `export_presets.cfg`) |
| gltf-transform wrapper | `~/media-stack/tools/vr/gltf` (wraps `~/.hermes/tools/node-26.12.1-darwin-arm64/bin/gltf-transform`, v4.5.1) |
| GLB optimizer | `~/media-stack/tools/vr/optimize_glb.sh` |
| WebXR room | `~/media-stack/vr/index.html` (+ `~/media-stack/vr/vendor/` Three.js), served at `http://127.0.0.1:8787/vr/` by the panel |
| Test asset (read-only) | `~/media-stack/vr/pig.glb` — 1,199,738 tris, 3× 4096² PNG, 77 MB |
| Scratch output dir | `~/media-stack/scratch/vr-test/` |

Verify in one shot:
```bash
/Applications/Godot.app/Contents/MacOS/Godot --headless --version && ls "$HOME/Library/Application Support/Godot/export_templates/4.7.2.stable/" && ~/media-stack/tools/vr/gltf --version
```
Expected: `4.7.2.stable.official.ed1daf0bf`, a file list containing `macos.zip` and `windows_release_x86_64.exe`, and `4.5.1`.

Never write into `~/media-stack/vr/pig.glb` or `~/media-stack/gold-standard/`. Never touch ComfyUI (:8188) or `~/media-stack/ComfyUI/models`.

## Recipes

### 1. Load a GLB in the Godot room (desktop fallback on the Mac)
Intent: open the Godot VR room on the Mac showing a given GLB, fit to 1.8 m, standing on the 1 m grid floor.
```bash
/Applications/Godot.app/Contents/MacOS/Godot --path ~/media-stack/vr-godot --xr-mode off -- /ABS/PATH/model.glb
```
(Omit the path after `--` to load the default `~/media-stack/vr/pig.glb`.) A window opens; WASD/QE move, hold right-mouse to look, Shift = fast. Close the window to exit.
Headless check (no window, 3 frames, prints and quits):
```bash
/Applications/Godot.app/Contents/MacOS/Godot --headless --xr-mode off --path ~/media-stack/vr-godot --quit-after 3 -- /ABS/PATH/model.glb 2>&1 | grep -E "XR_MODE|GLB_|ERROR"
```
Expected output (pig.glb):
```
XR_MODE desktop_fallback
GLB_INFO size_m=1.63x1.80x0.34 scale=1.799 tris=1199738
GLB_LOAD OK /Users/dcruse/media-stack/vr/pig.glb
```
Any `ERROR:` line or `GLB_LOAD FAILED` = the GLB is bad for Godot (see Pitfalls). `--xr-mode off` only suppresses the OpenXR-loader errors on this headset-less Mac; the exported builds leave XR on.

### 2. Export the Windows build for the SteamVR box
Intent: produce a single `VRGodotRoom.exe` (pck embedded) to copy to the RTX 4080 PC.
```bash
mkdir -p ~/media-stack/scratch/vr-test/export/win && /Applications/Godot.app/Contents/MacOS/Godot --headless --path ~/media-stack/vr-godot --export-release "Windows Desktop" ~/media-stack/scratch/vr-test/export/win/VRGodotRoom.exe > ~/media-stack/scratch/vr-test/export_win.log 2>&1; echo exit=$?; grep -c ERROR ~/media-stack/scratch/vr-test/export_win.log; ls -la ~/media-stack/scratch/vr-test/export/win/
```
Expected: `exit=0`, `0` errors, `VRGodotRoom.exe` ≈ 109 MB (`file` reports `PE32+ executable (GUI) x86-64`).
On the Windows box: SteamVR must be the active OpenXR runtime (SteamVR → Settings → OpenXR → "Set SteamVR as OpenXR runtime"), then run:
`VRGodotRoom.exe -- C:\path\to\model.glb` (no path → it looks for `%USERPROFILE%\media-stack\vr\pig.glb`; copy a GLB next to the exe and pass its path). Stdout shows `XR_MODE openxr` when the headset is driving.
macOS build (for flat testing only, no XR runtime on macOS):
```bash
/Applications/Godot.app/Contents/MacOS/Godot --headless --path ~/media-stack/vr-godot --export-release "macOS" ~/media-stack/scratch/vr-test/export/VRGodotRoom-macos.zip && unzip -qo ~/media-stack/scratch/vr-test/export/VRGodotRoom-macos.zip -d ~/media-stack/scratch/vr-test/export/mactest && "$HOME/media-stack/scratch/vr-test/export/mactest/VR Godot Room.app/Contents/MacOS/VR Godot Room" --xr-mode off -- /ABS/PATH/model.glb
```
Renderer: **Forward+** (`rendering/renderer/rendering_method="forward_plus"`) — the target is PC VR on an RTX 4080 where Forward+ gives full PBR, SDFGI/volumetrics headroom and 4× MSAA (`msaa_3d=2`); switch to Mobile only for standalone headsets (Quest). XR settings in `project.godot`: `xr/openxr/enabled=true`, `xr/shaders/enabled=true`, `xr/openxr/startup_alert=false` (so the desktop fallback runs instead of a modal when no runtime is found).

### 3. Optimize a GLB for VR budgets
Intent: cut tris to a target, cap texture size, dedup/prune/weld; print before/after.
```bash
~/media-stack/tools/vr/optimize_glb.sh /ABS/in.glb ~/media-stack/scratch/vr-test/out.glb --target-tris 100000 --tex 2048
```
Expected (pig.glb, ~5 s):
```
BEFORE: size=77.19MB tris=1,199,738 textures=4096x4096,4096x4096,4096x4096
simplify: 1199738 tris -> target 100000 (ratio 0.083351531751099)
AFTER:  size=21.82MB tris=100,000 textures=2048x2048,2048x2048,2048x2048
wrote /Users/dcruse/media-stack/scratch/vr-test/out.glb
```
Budgets: PC VR hero asset ≤ 100k–200k tris / 2048² textures; Quest ≤ 50k / 1024². Default output is a plain GLB (no mesh compression) so Godot and the local WebXR room both load it. `--meshopt` adds EXT_meshopt_compression (18.26 MB for the pig) but **Godot 4.7.2 cannot import it** — only use it for a Three.js viewer that registers `MeshoptDecoder`. Draco is never used (Godot cannot import it; slower/larger decoder than meshopt).
Full stats of any GLB: `~/media-stack/tools/vr/gltf inspect /ABS/file.glb` (tables for scenes/meshes/materials/textures).
Then confirm Godot loads the result with Recipe 1's headless check (expect `GLB_LOAD OK` and the new `tris=`).

### 4. Existing WebXR room (Three.js, browser)
Intent: view `~/media-stack/vr/pig.glb` in a browser / WebXR headset without Godot.
- URL: `http://127.0.0.1:8787/vr/` (panel "VR Room" tab). Page: `~/media-stack/vr/index.html`, which loads `./pig.glb` (hard-coded; to show another model copy/overwrite a GLB **into a scratch copy of the room**, never the gold `pig.glb`, or edit the `loader.load('./pig.glb'` line in a copy of `index.html`).
- Three.js is vendored in `~/media-stack/vr/vendor/` (`three.module.js`, `GLTFLoader.js`, `VRButton.js`, `OrbitControls.js`) — no CDN.
- WebXR only works in a secure context: `http://localhost` / `http://127.0.0.1` or HTTPS. A LAN URL like `http://192.168.x.x:8787/vr/` shows the room flat but the "Enter VR" button will not work. For a headset on the LAN use an HTTPS reverse proxy or port-forward to localhost on the headset's PC (e.g. `ssh -L 8787:127.0.0.1:8787`).
- No `MeshoptDecoder` is registered in `index.html`: only plain GLBs (optimize_glb.sh default) load there.

## Verify
```bash
cd ~/media-stack/vr-godot && /Applications/Godot.app/Contents/MacOS/Godot --headless --xr-mode off --path . --quit-after 3 2>&1 | grep -E "GLB_LOAD OK" && ls ~/media-stack/scratch/vr-test/export/win/VRGodotRoom.exe && echo TOOLKIT_OK
```
Expected last line: `TOOLKIT_OK`.

## Pitfalls (hit while building this)
- **Godot rejects meshopt/quantized GLBs**: `glTF: Can't import file ..., required extension 'EXT_meshopt_compression' is not supported` (same for `KHR_mesh_quantization`). Re-run `optimize_glb.sh` without `--meshopt`.
- **macOS export fails** with `Cannot export for universal or arm64 if ETC2 ASTC texture format is disabled` → `project.godot` must contain `textures/vram_compression/import_etc2_astc=true` under `[rendering]` (already set).
- **OpenXR loader errors on the Mac** (`RuntimeManifestFile::FindManifestFiles - failed ...`, `WARNING: OpenXR was requested but failed to start`) are normal here (no runtime installed). They are not script errors; pass `--xr-mode off` to silence them in tests.
- **Export templates .tpz is 1.28 GB** and GitHub throttles to ~0.3–10 MB/s while ComfyUI downloads run. `~/media-stack/tools/vr/tpz_partial.py URL OUTDIR 'macos\.zip$' 'windows_(release|debug)_x86_64(_console)?\.exe$' 'version\.txt$'` range-fetches only the needed entries (~300 MB) straight into the template dir layout.
- Godot was installed by unzip → `/Applications/Godot.app` → `xattr -dr com.apple.quarantine /Applications/Godot.app`. Homebrew now exists (`brew upgrade --cask godot` works only if you reinstall via `brew install --cask godot` first).
- Run `--headless --import` once after adding files to the project, or the first `--export-release` does the import itself (slower, but works).
- The npm global prefix here is the node dir: `~/.hermes/tools/node-26.12.1-darwin-arm64/bin/gltf-transform` — always call it through `~/media-stack/tools/vr/gltf` so PATH is right.
