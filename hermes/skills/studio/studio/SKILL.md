---
name: studio
description: "Use when making any asset on Dylan's Mac. Routes to tools."
version: 1.0.0
author: Jimmy
license: MIT
platforms: [macos]
metadata:
  hermes:
    tags: [studio, router, local-inference, comfyui, blender, godot, orcaslicer, mlx-audio, apple-silicon]
    category: studio
---

# Studio — the one-stop local asset pipeline (M3 Max, 64 GB)

Image, video, 3D, VR, 3D-print, SFX, music, voice: everything generative runs on this Mac.
**No cloud inference, ever** — if a recipe here cannot do it, say so; do not reach for an
API. Load this skill first, then the one specific skill the table points at. All commands
are copy-pasteable as written.

## When to Use

- Any request to create, convert, edit, upscale, slice, rig, or preview an asset on this Mac.
- Deciding *which* local tool/model fits a request before loading a deeper skill.
- Checking whether the generation services are up and which models are installed.

## Route by need

| You need | Command / tool | Detail skill |
|---|---|---|
| Image from text (fast, default) | `gen image "prompt"` (Z-Image-Turbo, ~20 s) | this file |
| Image, highest quality / text in image | `gen image "prompt" --model flux` (~3-4 min) | this file |
| Image guided by a sketch/photo edges | `gen control "prompt" --image ref.png` | this file |
| Edit an existing image / turnaround views | Qwen-Image-Edit (ComfyUI UI template) | `local-media-stack` (its qwen-image-edit-apose reference) |
| Upscale image | `gen upscale in.png --method esrgan` (fast) / `--method seedvr2` (diffusion) | this file |
| Video clip from text or image | `gen video "prompt" [--image start.png]` (Wan 2.2 5B, slow) | this file |
| Edit/cut/caption/concat video | `vid …`, Blender VSE edit list | `studio-video-edit` |
| Sound effect | `gen sfx "prompt" --seconds 8` | this file |
| Music / full song with lyrics | `gen music "tags" --lyrics "..."` (ACE-Step 1.5) | this file |
| Speech, voice clone, transcription | `voice say/clone/transcribe/enhance` | `studio-voice` |
| 3D model from a photo | TRELLIS.2 via ComfyUI UI (`scratch/run_trellis2.py`) | `local-media-stack` (gold-standard recipe) |
| Fix / rig / render a mesh | Blender via `~/media-stack/bin/blender -b -P script.py` | `local-media-stack`, `blender` |
| Parametric part → STL → G-code | `cad_examples/*.py`, `meshcheck.py`, `slice --preset bambu|generic` | `studio-3d-print` |
| View asset in VR / build SteamVR app | Godot room, `optimize_glb.sh`, WebXR room | `studio-vr` |
| Vector / raster hand-editing (human) | Inkscape, Krita, Audacity, OpenSCAD, MeshLab in /Applications | — |

## Services (check first, start if down)

```bash
stack status                 # ComfyUI :8188, mlx-audio :8000, panel :8787
stack start comfy            # images / video / sfx / music / 3D
stack start audio            # TTS / STT / voice clone
gen status                   # which ComfyUI model sets are installed + queue depth
fetch-models --list          # ✓/✗ every model in models/manifest.json; `fetch-models` downloads the ✗
```

Panel: http://127.0.0.1:8787 — Studio page. Tabs Image / Video / 3D & VR / Sound / Voice each have
a run form (same `gen`/`voice` commands underneath), a Jobs list, and an output gallery with
inline preview (click any item; GLB/STL open in `/vr/view.html`). The header shows the live
ComfyUI progress bar (step N/M) for anything submitted as client `gen-cli` — `gen` and the
Hermes plugin do; ComfyUI-UI jobs show an indeterminate bar. Models tab = manifest inventory
with present / downloading / missing. `/legacy` is the old page.

**Pitfall:** ComfyUI only sends `progress`/`executing` websocket events to the socket whose
`clientId` submitted the prompt. A passive listener sees queue counts only. Submit with a
fixed `client_id` and listen under the same id (`control/studio.py`).

## `gen` — one CLI for every ComfyUI pipeline

`~/media-stack/tools/comfy/gen` (also on PATH as `gen`). Prints exactly one JSON line:
`{"ok": true, "files": [...], "seconds": 53.1, "prompt_id": "..."}` or `{"ok": false, "error": "..."}`.
Outputs land in `~/media-stack/output/<kind>/`. It waits for an idle ComfyUI queue before
submitting (`--now` to skip) because one GPU is shared with the Telegram session.

```bash
gen image "a brass compass on a map, soft window light"                      # Z-Image-Turbo, 1024², 8 steps
gen image "..." --model klein --w 1344 --h 768 --n 2                          # FLUX.2 klein 4B, 4 steps
gen image "..." --model flux --seed 42                                        # Flux dev fp8, 20 steps, slow
gen control "same scene, watercolor" --image photo.png --mode canny --save-control
gen control "..." --image depth_or_pose_map.png --mode raw                    # you supply the control map
gen upscale out.png --method esrgan --scale 2                                 # RealESRGAN x4 → rescaled to 2x
gen upscale out.png --method ultrasharp                                       # 4x-UltraSharp (crisper, more hallucination)
gen upscale out.png --method seedvr2 --scale 2                                # SeedVR2 3B diffusion upscaler (slow, best)
gen video "a hog trots through a barn, handheld, golden hour" --w 1280 --h 704 --frames 121 --fps 24
gen video "..." --image start.png                                             # image-to-video, same model
gen sfx "heavy wooden door creaks open, stone hall reverb" --seconds 6        # Stable Audio Open 1.0
gen sfx "..." --model sa3 --seconds 30                                        # Stable Audio 3 medium (music/ambience too, up to 150 s)
gen music "lo-fi hip hop, warm rhodes, vinyl crackle" --seconds 90 --bpm 85 --lyrics "[inst]"
gen music "indie folk, acoustic guitar, female vocal" --lyrics-file song.txt --seconds 150 --key "G major"
```

Lyrics use ACE-Step section tags: `[Verse]`, `[Chorus]`, `[Bridge]`, `[inst]` for instrumental.
`--key` must be one of the 34 listed by `gen music -h` (e.g. `A minor`); `--timesig` is 2/3/4/6.

**Measured on this machine, idle box, model load included (Nov 2026):** see the table in
`references/benchmarks.md`. Re-measure before claiming a regression — a download writing to
disk inflates every timing 2-3×.

## Rules that always apply

- **State which half is local.** Generation is on-device; this conversation's reasoning is a cloud model. Say so when reporting.
- **One GPU, two sessions.** Desktop and Telegram both drive ComfyUI. `gen` queues; hand-rolled scripts must poll `GET :8188/queue` until empty.
- **Check the file, not the status.** A ComfyUI run can report success and write nothing. `gen` already fails on that; do the same in any custom script.
- **Verify by looking.** `vision_analyze` the output image/frame; `voice transcribe` the audio you generated; `meshcheck.py` the STL. Never report a result you have not opened.
- **Downloading assets is fine; generating via cloud is not.** Fonts, HDRIs, models, JS libs — fetch freely. Inference stays here.
- **Deliverables must not phone home.** Any HTML/VR page: vendor its JS, then prove it with `performance.getEntriesByType('resource')`.
- **Models only appear after download completes.** `fetch-models` writes `.part` then renames; ComfyUI (Oct-2026 build) picks new files up without a restart — if a loader still rejects a filename, `stack restart comfy` while the queue is empty.

## Memory budget (64 GB unified)

| Resident set | ~GB | Note |
|---|---|---|
| Z-Image-Turbo + Qwen3-4B encoder | 21 | default image path |
| Flux dev fp8 | 27 | evicts Z-Image |
| Qwen-Image-Edit 2509 | 30 | editor; run alone |
| Wan 2.2 5B + umT5 | 18 | video |
| TRELLIS.2 + DINOv3 | 8 + unwrap spikes to 40+ | 3D; watch UV chart count |
| ACE-Step 1.5 AIO | 10 | music |
| Stable Audio 3 medium | 10 | sfx/music |
| mlx-audio (Kokoro + Whisper + Qwen3-TTS) | 6 | separate process |

Switching families pays the load cost again. `stack free` unloads ComfyUI models without
stopping the server. Swap in use (panel → Resources) is the honest warning.

## Layout

```
~/media-stack/
├── bin/            stack, fetch-models, blender (wrapper), restore-known-good
├── tools/comfy/gen         image/control/upscale/video/sfx/music CLI
├── tools/video/            vid, vse_build.py, transcribe_srt.py
├── tools/voice/voice       say/voices/clone/transcribe/enhance
├── tools/print/            cad_examples/, meshcheck.py, slice
├── tools/vr/               gltf, optimize_glb.sh
├── tools/.venv             python 3.12: build123d, trimesh, moviepy, pedalboard, librosa
├── vr/                     WebXR room (Three.js vendored)   vr-godot/  Godot 4.7 OpenXR room
├── models/manifest.json    every model the stack needs (url, path, size)
├── output/<kind>/          gen outputs      ComfyUI/output/   raw ComfyUI outputs
├── gold-standard/          approved assets — copy, never overwrite
└── STATE.md                handoff state — read before continuing 3D/VR work
```
