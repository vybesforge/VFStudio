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
| Image from text (fast, default) | `gen image "prompt"` (Z-Image-Turbo, ~50 s) · `--model klein` (FLUX.2 klein, ~23 s) | this file |
| Image, highest quality / text in image | `gen image "prompt" --model flux` (~3-4 min) | this file |
| Image guided by a sketch/photo edges | `gen control "prompt" --image ref.png` | this file |
| Edit an existing image (change X, keep the rest) / turnaround views | `gen edit in.png "instruction" --fast` (Qwen-Image-Edit 2509, Q4 GGUF; `--ref2 b.png` for multi-image) | this file; apose recipe in `local-media-stack` |
| Upscale image | `gen upscale in.png --method esrgan` (fast) / `--method seedvr2` (diffusion) | this file |
| Video clip from text or image | `gen video "prompt" [--image start.png]` (Wan 2.2 5B, slow) | this file |
| Edit/cut/caption/concat video | `vid …`, Blender VSE edit list | `studio-video-edit` |
| Sound effect | `gen sfx "prompt" --seconds 8` | this file |
| Music / full song with lyrics | `gen music "tags" --lyrics "..."` (ACE-Step 1.5) | this file |
| Speech, voice clone, transcription | `voice say/clone/transcribe/enhance` | `studio-voice` |
| Split a song into stems / karaoke (instrumental, a cappella) | `stems split song.flac` (drums/bass/other/vocals, ~7 s per 30 s) · `stems karaoke song.flac` (no_vocals) | `studio-stems` |
| Fiction, screenplay, game dialogue, lore (uncensored, local) | `scribe prose|outline|chapter|screenplay|dialogue|lore|revise` | `studio-writing` |
| Train a LoRA for a recurring subject/style | `lora train --dataset DIR --name NAME` → `gen image … --lora NAME` | `studio-lora` |
| Look at an image / camera, OCR, compare renders (local) | `see describe|ask|ocr|compare|snap` | `studio-vision` |
| 3D model from a photo | TRELLIS.2 via ComfyUI UI (`scratch/run_trellis2.py`) | `local-media-stack` (gold-standard recipe) |
| Fix / rig / render a mesh | Blender via `~/media-stack/bin/blender -b -P script.py` | `local-media-stack`, `blender` |
| Parametric part → STL → G-code | `cad_examples/*.py`, `meshcheck.py`, `slice --preset bambu|generic` | `studio-3d-print` |
| View asset in VR / build SteamVR app | Godot room, `optimize_glb.sh`, WebXR room | `studio-vr` |
| 2D/3D game prototype, run/export Godot headless | `~/media-stack/game/new_project.sh 2d\|3d Name dest` | `studio-game` |
| Playable 3D game in the browser (Three.js + TS + Vite) | hand-written `package.json` + `npm install`, procedural textures / WebAudio | `browser-3d-game` |
| Auto-rig + test cycle → GLB, Grease Pencil 2D, sprite sheets, Krita/Tahoma2D path | `tools/anim/rigify_auto.py`, `gp_anim.py`, `spritesheet.py` | `studio-animation` |
| Vector / raster hand-editing (human) | Inkscape, Krita, Audacity, OpenSCAD, MeshLab in /Applications | — |

## Services (check first, start if down)

```bash
stack status                 # ComfyUI :8188, mlx-audio :8000, writer LLM :8081, vision VLM :8082, panel :8787
stack start comfy            # images / video / sfx / music / 3D
stack start audio            # TTS / STT / voice clone
stack start llm              # uncensored 27B writer (16 GB) · stack start vision = Qwen3-VL 8B (5 GB)
gen status                   # which ComfyUI model sets are installed + queue depth
fetch-models --list          # ✓/✗ every model in models/manifest.json; `fetch-models` downloads the ✗
```

Panel: http://127.0.0.1:8787 — **VF Studio** page (`control/studio.html` + `studio.py`). Tabs
Image / Video / 3D & VR / Sound / Voice / Write / Vision / Train each have a run form (same CLI args
underneath), a Jobs list with cancel, and an output gallery with inline preview (GLB/STL open in
`/vr/view.html`; 3D items also get "room" / "rig" buttons). Train = dataset upload → `lora train`
job → LoRA picker on the Image form. **Every path field has an Upload… button** (`/api/studio/upload?kind=image|voice|model|dataset`)
and the Voice tab records from the mic — Dylan uses the page himself, so a path-only field is a bug:
the first thing he asks is "how do I get my own image/voice in". Code edits need `stack restart panel`
(uvicorn does not hot-reload); never `pkill python` — it takes the gateway down with it. Header = live ComfyUI progress bar
(step N/M) for anything submitted as client `gen-cli` — `gen` and the Hermes plugin do; ComfyUI-UI
jobs show an indeterminate bar. Models tab = manifest + HF inventory. **Services tab = live start/stop cards + an Endpoints block**
that lists every URL another local program or page can be pointed at (TTS, STT, voice clone, ComfyUI,
writer LLM, VLM, this panel's own API) with per-row **Copy URL**, a **Details** panel (routes + a
working curl), and **Copy all → .env / JSON**; a host switch flips every link between `127.0.0.1` and
the LAN IP. Source of truth is the `ENDPOINTS` list in `control/panel.py` served at `/api/endpoints` —
add a service there, not in the HTML, or the page and reality drift. Resources tab has
**Unload all models** and **Stop everything**. There is one page; never add a second UI or a
"legacy" copy — Dylan asks for consolidation and removes duplicates.

**Branding (standing preference):** anything web-facing in the stack carries the VybesForge look —
vendored `control/brand/*.png` (VF monogram, never hot-linked), palette navy `#02060f/#0b121d`,
forge orange `#fd6c0f`, amber `#ffb000`, cyan `#29d5e9`, magenta `#bf338a`, title "VF Studio",
footer link to vybesforge.com.

**Pitfall:** ComfyUI only sends `progress`/`executing` websocket events to the socket whose
`clientId` submitted the prompt. A passive listener sees queue counts only. Submit with a
fixed `client_id` and listen under the same id (`control/studio.py`).

## `gen` — one CLI for every ComfyUI pipeline

`~/media-stack/tools/comfy/gen` (also on PATH as `gen`). Prints exactly one JSON line:
`{"ok": true, "files": [...], "seconds": 53.1, "prompt_id": "..."}` or `{"ok": false, "error": "..."}`.
Outputs land in `~/media-stack/output/<kind>/`. It waits for an idle ComfyUI queue before
submitting (`--now` to skip) because one GPU is shared with the Telegram session.

```bash
gen image "a brass compass on a map, soft window light"                      # Z-Image-Turbo, 1024², 8 steps, ~50 s
gen image "..." --model klein --w 1344 --h 768 --n 2                          # FLUX.2 klein 4B, 4 steps, ~23 s — fastest
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
disk inflates every timing 2-3×. **Benchmark alone:** another session or subagent running `gen`
in between evicts the weights, so a "warm" second run reloads 20 GB and the number is garbage —
check `gen status` queue is 0 and `logs/comfy.log` shows no `Requested to load` for the model
between your runs. When delegating, give at most ONE subagent GPU-heavy work at a time.

## Rules that always apply

- **State which half is local.** Generation is on-device; this conversation's reasoning is a cloud model. Say so when reporting.
- **One GPU, two sessions.** Desktop and Telegram both drive ComfyUI. `gen` queues; hand-rolled scripts must poll `GET :8188/queue` until empty.
- **Check the file, not the status.** A ComfyUI run can report success and write nothing. `gen` already fails on that; do the same in any custom script.
- **Verify by looking.** `vision_analyze` the output image/frame; `voice transcribe` the audio you generated; `meshcheck.py` the STL. Never report a result you have not opened.
- **Downloading assets is fine; generating via cloud is not.** Fonts, HDRIs, models, JS libs — fetch freely. Inference stays here.
- **Deliverables must not phone home.** Any HTML/VR page: vendor its JS, then prove it with `performance.getEntriesByType('resource')`.
- **Models only appear after download completes.** `fetch-models` writes `.part` then renames; ComfyUI (Oct-2026 build) picks new files up without a restart — if a loader still rejects a filename, `stack restart comfy` while the queue is empty.
- **Model folders are per loader, not per "kind".** `ModelPatchLoader` (Z-Image ControlNet Union) reads `models/model_patches/`, not `controlnet/`. When a loader says `Value not in list: … not in []`, the file is in the wrong folder; check `/object_info/<Loader>` for the list it sees.
- **ComfyUI drops a failing branch and still reports success.** If one output node fails validation the rest runs and `/history` shows `status_str: success` with only the surviving outputs. `gen` fails on `node_errors` in the submit response; do the same in any custom script.
- **A job runner must catch its own spawn.** Wrap `Popen` in try/except and mark the job failed — a missing executable otherwise leaves a job "running" forever with an empty log, which reads as a hung model.
- **Qwen3.x local models think by default.** Disable it per request (`chat_template_kwargs.enable_thinking=false`) for prose/vision answers, or the reasoning consumes the whole `max_tokens` and the reply is empty.
- **fp8 weights are a trap on Apple Silicon.** MPS has no fp8 kernel, so ComfyUI upcasts `*_fp8_e4m3fn.safetensors` to bf16 in memory (a 20 GB file becomes 39 GB resident and swaps). For any model over ~10 GB prefer a Q4/Q5 **GGUF** via the ComfyUI-GGUF node pack (`UnetLoaderGGUF`, files in `models/unet/`) — same quality class, ~⅓ the memory. Check `logs/comfy.log` "loaded completely; N MB" against the file size to catch it.
- **Rewriting git history resets the working tree.** `git filter-repo` (and `filter-branch`) check out the rewritten HEAD, deleting every file that was tracked before and is now purged — including local assets you meant to keep. Copy `gold-standard/`, `rig/`, any tracked GLBs aside first, and keep local assets gitignored from day one so they are never tracked at all.
- **Use absolute paths / `workdir` when subagents share the box.** They create and delete scratch dirs; a terminal whose cwd was deleted fails every relative command with a misleading `cd` error.

## Adding a capability (do all of these, in this order — a half-wired tool is what gets reported as "broken")

1. **CLI first**, in `tools/<area>/<name>`: one JSON line out (`{"ok":…,"files":[…],"seconds":…}`), a
   `status` subcommand, outputs under `output/<kind>/`, waits for the shared GPU where relevant.
   Pick the name with `command -v <name>` first — macOS already owns `write`, `say`, `open`, `look`,
   `install`; a collision runs the system binary silently. Shebang = the venv python; the installer
   rewrites shebangs, so keep them on line 1 only.
2. **Portable paths**: resolve `ffmpeg`/`node`/`uv` as env var → `PATH` → Hermes-bundled glob; never
   hard-code `~/.hermes/tools/<tool>-<version>` — it does not exist on the next machine.
3. **Models**: ComfyUI files → `models/manifest.json` (then `fetch-models`); MLX/HF repos →
   `models/hf-models.txt` (fetched with `HF_HUB_DISABLE_XET=1 hf download`). Judge presence with
   `ls -laL <hub>/snapshots/*/`, not `du` — the symlinked cache under-reports by 1000×.
4. **Service** (if a server): add to `SERVICES` in `control/panel.py` (`stack start <name>` then works),
   bind `127.0.0.1`, and add it to `unload_all` if it holds weights.
5. **Panel**: a tab or form in `studio.html`, job kind in `studio.py` (`_build_cmd`, `ROOTS`, `EXT`,
   `TOOLS`), inventory row. Jobs run the CLI, so the page and the skill can never disagree.
6. **Installer**: venv/package step, brew cask, symlink, `install.sh` header comment; run
   `bash -n install.sh` and then `./install.sh --no-apps` here — it must be a no-op on a built box.
7. **Skill**: `studio-<area>` in the repo format (description ≤ 60 chars, exact commands, measured
   numbers, pitfalls you hit) + a row in this table + the name in `SKILLS=` of `bin/sync-hermes`;
   `bin/sync-hermes export`; commit. A `skill_manage` batch is atomic — if a sibling patch fails, the
   create is rolled back silently; confirm with `skills_list` before exporting.

## Publishing

Repo: `~/media-stack` → `github.com/vybesforge/VFStudio` (`main`). **Code, docs and skills only —
local assets never go to GitHub** (standing rule): `*.glb`, `gold-standard/`, `rig/joints_*.json`,
`output/`, `train/{datasets,runs,models,.venv}`, model weights, venvs are gitignored. Before every
push run `git rev-list --objects --all | git cat-file --batch-check='%(objecttype) %(objectsize) %(rest)' | awk '$1=="blob" && $2>1000000'`
— anything over ~1 MB that is not vendored JS is a mistake; `*.glb` in the room counts even when
"small". GitHub warns at 50 MB and refuses at 100 MB, but the rule is about the repo's purpose, not the limit. Dylan keeps the GitHub token in a
file on his Desktop; read it, pass it through a one-shot `git -c credential.helper=…` so it never lands
in `.git/config` or shell history, and never echo it. A fine-grained PAT must have **Contents: Read
and write** on the repo — `git push` and `POST /git/blobs` both 403 without it even though
`/repos/...` reports `push: true` (that field describes the user, not the token).

## Image editing — `gen edit` (Qwen-Image-Edit 2509)
```bash
gen edit output/image/zimage_00002_.png "Make it a snowy winter night with the barn lit from inside; keep the hog exactly the same" --fast --seed 3
# --fast = Lightning LoRA, 4 steps (default 20 steps, cfg 4). --ref2 b.png adds a second reference ("put the object from image 2 into image 1").
```
Heaviest model in the stack. **Run it alone**: `curl -s -X POST -H 'Content-Type: application/json' -d '{}' http://127.0.0.1:8787/api/studio/unload-all` first.
It prefers `ComfyUI/models/unet/Qwen-Image-Edit-2509-Q4_K_M.gguf` (13 GB, needs the ComfyUI-GGUF node pack — installed) and falls back to the fp8 safetensors (`--fp8` forces it). Measured fp8 path: fp8 has no MPS kernel, ComfyUI upcasts to **39 GB bf16**, 10 GB swap, 26–65 s/step → 5–9 min per edit even with `--fast`. Result quality was correct (scene changed, subject identical). Panel: Image tab → "Edit" card; upload a starting image with the Upload… button.

## Which model for which job (and what was rejected)
`references/model-choices.md` — installed defaults, why, licences, Mac-fit math, rejected alternatives and the 10-minute re-audit procedure. Read it before proposing a model swap.

## Where to save anything you make (non-negotiable)
The VF Studio panel shows a file only if it is under one of these trees; it sorts it into a tab by extension:

| Save under | Shows in panel tab |
|---|---|
| `~/media-stack/output/image/` (also `control/`, `upscale/`, `edit/`, `renders/`) — png/jpg/webp | Image |
| `~/media-stack/output/video/` — mp4/webm/gif | Video |
| `~/media-stack/output/3d/` — glb/gltf/stl/obj | 3D & VR ("set in room", "rig") |
| `~/media-stack/output/sfx/`, `music/`, `stems/` — wav/flac/mp3 | Sound |
| `~/media-stack/output/voice/` — wav/mp3 | Voice |
| `~/media-stack/output/text/` — md/txt/json/fountain/srt | Write |
| `~/media-stack/output/camera/` | Vision |
| `~/media-stack/game/<project>/**` (not node_modules/dist/build) | 3D & VR → Game projects + the galleries above |

Any subfolder inside those trees is fine (`output/renders/blender/hero.png` still lands in Image). `scratch/`
and `ComfyUI/output/` are scanned too but treat them as temporary. Files written anywhere else — home,
Desktop, `/tmp`, another repo — are **invisible in the panel**. The `gen`, `voice`, `vid`, `scribe`, `see`,
`stems`, `lora` CLIs already default to the right folder; when you write a file yourself (Blender render,
ffmpeg output, a script), pass an `--out` under `~/media-stack/output/<kind>/`. Tell Dylan the path
relative to `~/media-stack/` — each gallery card shows that same folder.

## Memory budget (64 GB unified)

| Resident set | ~GB | Note |
|---|---|---|
| Z-Image-Turbo + Qwen3-4B encoder | 21 | default image path |
| Flux dev fp8 | 27 | evicts Z-Image |
| Qwen-Image-Edit 2509 fp8 (upcast) / Q4 GGUF | 47 / ~21 | editor; fp8 swaps 10 GB and runs 26-65 s/step — use the GGUF |
| Wan 2.2 5B + umT5 | 18 | video |
| TRELLIS.2 + DINOv3 | 8 + unwrap spikes to 40+ | 3D; watch UV chart count |
| ACE-Step 1.5 AIO | 10 | music |
| Stable Audio 3 medium | 10 | sfx/music |
| mlx-audio (Kokoro + Whisper + Qwen3-TTS) | 6 | separate process |
| writer LLM (Qwen3.8 27B 4-bit) | 16 | stop before Flux dev / Qwen-Edit |
| vision VLM (Qwen3-VL 8B 4-bit) | 5 | |

**Out of memory?** Panel → Resources → "Unload all models / free memory" (ComfyUI `/free`, LLM+VLM stopped, mlx-audio recycled; measured 25 GB back in one click) or `curl -X POST :8787/api/studio/unload-all`.

Switching families pays the load cost again. `stack free` unloads ComfyUI models without
stopping the server. Swap in use (panel → Resources) is the honest warning.

## Layout

```
~/media-stack/
├── bin/            stack, fetch-models, blender (wrapper), restore-known-good
├── tools/comfy/gen         image/control/upscale/video/sfx/music CLI
├── tools/video/            vid, vse_build.py, transcribe_srt.py
├── tools/voice/voice       say/voices/clone/transcribe/enhance
├── tools/audio/stems       split/karaoke/status (demucs, own venv stems/.venv)
├── tools/print/            cad_examples/, meshcheck.py, slice
├── tools/vr/               gltf, optimize_glb.sh
├── tools/llm/scribe        prose/outline/chapter/screenplay/dialogue/lore/revise (mlx-lm :8081)
├── tools/vision/see        describe/ask/ocr/compare/snap (mlx-vlm :8082 + imagesnap)
├── tools/anim/             rigify_auto.py, gp_anim.py, spritesheet.py, pngseq_to_vse.py
├── game/                   Godot 2D/3D templates, new_project.sh
├── control/                panel.py, studio.py, studio.html, brand/
├── hermes/                 image_gen plugin + all studio skills (bin/sync-hermes export|install)
├── install.sh, INSTALL.md  reproduce the whole stack on another Apple Silicon Mac
├── tools/.venv             python 3.12: build123d, trimesh, moviepy, pedalboard, librosa
├── vr/                     WebXR room (Three.js vendored)   vr-godot/  Godot 4.7 OpenXR room
├── models/manifest.json    every model the stack needs (url, path, size)
├── output/<kind>/          gen outputs      ComfyUI/output/   raw ComfyUI outputs
├── gold-standard/          approved assets — copy, never overwrite
└── STATE.md                handoff state — read before continuing 3D/VR work
```
