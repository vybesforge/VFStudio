# media-stack — a one-stop local studio for Apple Silicon

Image · video · 3D · VR · 3D-print · sound FX · music · voice, all generated **on the
machine** (no cloud inference), all drivable by an AI agent through plain CLIs and a web panel.
**What this repo is:** the studio *loadout* — installer, model manifest, CLIs, panel, skills — so another machine can run the same AI-drivable asset pipeline. **What it is not:** the things made with it. Games (`game/<project>`), models, GLBs, LoRAs, datasets and outputs stay local by `.gitignore`.

Built and measured on an M3 Max / 64 GB; see [INSTALL.md](INSTALL.md) to reproduce it on another Mac, or [INSTALL-UBUNTU.md](INSTALL-UBUNTU.md) for an NVIDIA Linux box (ported on paper, not yet run).

```
./install.sh [--all-models] [--hermes]      # fresh Mac → working studio
stack panel                                  # http://127.0.0.1:8787
```

## What's inside

| Need | Command | Engine (local) |
|---|---|---|
| Image, fast | `gen image "prompt"` | Z-Image-Turbo (8 steps) · FLUX.2 klein 4B (`--model klein`) |
| Image, best | `gen image "prompt" --model flux` | Flux dev fp8 |
| Image, guided | `gen control "prompt" --image sketch.png` | Z-Image + Fun ControlNet Union (canny / raw map) |
| Image edit / turnarounds | ComfyUI UI template | Qwen-Image-Edit 2509 (+ multi-angle LoRA) |
| Upscale | `gen upscale in.png --method esrgan\|ultrasharp\|seedvr2` | RealESRGAN · 4x-UltraSharp · SeedVR2 3B |
| Video | `gen video "prompt" [--image start.png]` | Wan 2.2 TI2V 5B (720p) |
| Video edit | `vid trim\|concat\|overlay-text\|add-audio\|subtitles\|…`, `vse_build.py` | ffmpeg 9 · Blender 5.2 VSE |
| Sound FX | `gen sfx "prompt" [--model sa3]` | Stable Audio Open 1.0 · Stable Audio 3 medium |
| Music | `gen music "tags" --lyrics "…"` · `stack music "caption"` | ACE-Step 1.5 · MiniMax-Music (mlx) |
| Voice | `voice say\|clone\|transcribe\|enhance` | Kokoro · Qwen3-TTS (clone) · Whisper large-v3-turbo |
| Photo → 3D | ComfyUI TRELLIS.2 template (`scratch/run_trellis2.py`) | TRELLIS.2 + DINOv3 + BiRefNet |
| Mesh repair / rig / render | `bin/blender -b -P …` | Blender 5.2 |
| CAD → STL → G-code | `tools/print/cad_examples/*.py` · `meshcheck.py` · `slice --preset bambu\|generic` | build123d · trimesh · OrcaSlicer 2.4 CLI |
| VR | `vr-godot/` · `tools/vr/optimize_glb.sh` · WebXR room `vr/` (any GLB, joint picker, controllers) | Godot 4.7 OpenXR · gltf-transform · Three.js |
| Games 2D/3D | `game/new_project.sh 2d\|3d <name> <dest>`, templates with headless run/export | Godot 4.7 |
| Animation | `tools/anim/rigify_auto.py` · `gp_anim.py` · `spritesheet.py` · `pngseq_to_vse.py` | Blender Rigify + Grease Pencil · Krita · Tahoma2D |
| Writing (uncensored) | `scribe prose\|outline\|chapter\|screenplay\|dialogue\|lore\|revise` | Qwen3.8-27B-Uncensored (mlx-lm, :8081) |
| Vision + camera | `see describe\|ask\|ocr\|compare\|snap` | Qwen3-VL-8B (mlx-vlm, :8082) · imagesnap |
| Image editing | `gen edit in.png "instruction" --fast` | Qwen-Image-Edit 2509 (Q4 GGUF via ComfyUI-GGUF) |
| Stems / karaoke | `stems split\|karaoke song.flac` | Demucs htdemucs (MPS) |
| LoRA training | `lora train --dataset DIR --name NAME` → `gen image --lora NAME` | ostris ai-toolkit (MPS) |

Every `gen` call prints one JSON line (`{"ok":true,"files":[…],"seconds":…}`), waits for an idle
GPU queue, and fails loudly when ComfyUI reports success without writing a file.

## The panel (`control/`)

http://127.0.0.1:8787 — one origin, tabs per modality:

| Tab | Contents |
|---|---|
| Image / Video / Sound / Voice / Write / Vision | run form (same args as the CLI) · jobs list with cancel · gallery with inline preview · camera snap |
| 3D & VR | WebXR room (iframe + full screen) · joint picker · GLB/STL viewer · meshes & prints gallery · "set in room" |
| Models | manifest inventory: present / downloading / missing per model, HF-cached audio models, tool checklist |
| Services | start / stop / restart / logs for ComfyUI, mlx-audio, writer LLM, vision VLM |
| Resources | CPU, GPU (IOAccelerator), memory, swap, disk, top processes · **Unload all models / Stop everything** |

The header shows the **live ComfyUI progress bar** (step N/M, elapsed, queue depth). It works
because `gen` and the Hermes plugin submit with `client_id: gen-cli` and the panel's websocket
listens under the same id — ComfyUI only sends per-step progress to the submitting client.

## Daily use

```bash
stack status | start comfy | start audio | stop comfy | free | logs comfy 100 | panel
gen status                      # which model sets are installed + queue
fetch-models --list             # ✓/✗ per manifest entry;  fetch-models  downloads the ✗
voice voices                    # Kokoro voice list
```

Outputs: `output/<kind>/` (gen), `ComfyUI/output/` (raw), `scratch/` (experiments).

## For AI agents (Hermes)

`hermes/` holds the `image_gen` plugin and the skills; `bin/sync-hermes install|export`
moves them in and out of `~/.hermes`. The **`studio`** skill is the entry point and routes
to `studio-video-edit`, `studio-voice`, `studio-3d-print`, `studio-vr`, `studio-game`,
`studio-animation`, `studio-writing`, `studio-vision` and `local-media-stack` (deep 3D reference). Skills are written for a
weaker model: exact commands, exact paths, expected output, measured pitfalls.

## Services

| Service | Port | Protocol |
|---|---|---|
| ComfyUI | 8188 | `POST /prompt`, `GET /history/{id}`, `GET /queue`, `POST /free`, `ws /ws?clientId=` |
| mlx-audio | 8000 | OpenAI-compatible `/v1/audio/speech`, `/v1/audio/transcriptions`; models by HF repo id, loaded on demand |
| writer LLM | 8081 | `mlx_lm.server`, OpenAI-compatible chat; Qwen3.8-27B-Uncensored 4-bit (`stack start llm`) |
| vision VLM | 8082 | `mlx_vlm.server`, OpenAI-compatible chat with image parts; Qwen3-VL-8B 4-bit (`stack start vision`) |
| panel | 8787 | FastAPI; `PANEL_HOST=0.0.0.0 stack panel` exposes it to the LAN (WebXR still needs localhost/HTTPS) |

## Hard-won constraints

- One GPU, shared by every session: poll `GET :8188/queue` before submitting (`gen` does).
- Never benchmark while `fetch-models` is writing — disk contention inflates timings 2–3×.
- Switching model families reloads weights (Flux dev 27 GB, Qwen-Edit 30 GB, Z-Image 21 GB);
  `stack free` hands memory back without stopping the server.
- Never symlink Blender into PATH — use `bin/blender` (sets up the bundled Python).
- `UnwrapMesh` OOMs on dense meshes: decimate first, watch UV *chart count*, not face count.
- Hunyuan3D / `SaveGLB` write no `NORMAL` attribute — the Blender repair pass fixes it.
- Full history, measurements and the approved gold-standard asset recipe: `STATE.md` and the
  `local-media-stack` skill.
