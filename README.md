# VF Studio — detect the machine, install what fits

Image, video, 3D, print, sound, music, and voice, generated **on the machine** (no cloud inference).
Windows, Linux, and Mac each get the engine that matches the probe: CUDA, ROCm, MLX, or CPU.

**What this repo is:** the studio loadout — installer, model manifest, CLIs, panel, skills — so another machine can run the same local pipeline. **What it is not:** the things made with it. Games, weights, and outputs stay local.

```bash
git clone <your-fork-url> ~/media-stack && cd ~/media-stack
bin/forge-recommend                         # this machine: OS, RAM, GPUs, free disk, tiers
bin/fetch-models --dry-run --profile auto   # what would download; stops if a license needs a login
bin/fetch-models --profile auto             # essentials + quality that fit
stack panel                                 # http://127.0.0.1:8787
```

| OS | Install |
|---|---|
| Apple Silicon | `./install.sh` (Homebrew, MLX for voice / writer / vision, ComfyUI for diffusion) |
| Linux | `python3 tools/forge/install.py` then the CUDA or ROCm steps in [INSTALL-UBUNTU.md](INSTALL-UBUNTU.md) |
| Windows | `powershell -File install.ps1` — probe and panel. `fetch-models` runs in Git Bash |

The probe never assumes a particular card. It uses the largest GPU, not the sum. `VF_GPU=1` picks another index. Apple Silicon keeps MLX where it is the right engine. NVIDIA and AMD keep ComfyUI for diffusion and use speaches plus llama-server for voice, writing, and vision. The uncensored writer is labeled: it is the Apple default, and opt-in everywhere else (`VF_UNCENSORED=1`, `scribe --uncensored`).

Checklist: [SMOKE.md](SMOKE.md). Apple Silicon detail: [INSTALL.md](INSTALL.md). CUDA and ROCm detail: [INSTALL-UBUNTU.md](INSTALL-UBUNTU.md).

Gated downloads: `huggingface-cli login` or `HF_TOKEN`. The token is not stored in the repo. `VF_SKIP_GATE=1` continues when you know the URL is public.

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
| Games | `game/new_project.sh 2d\|3d\|web` | Godot 4 (desktop) · Three.js (browser) |
| Animation | `tools/anim/rigify_auto.py` · `gp_anim.py` · `spritesheet.py` · `pngseq_to_vse.py` | Blender Rigify + Grease Pencil · Krita · Tahoma2D |
| Writing (uncensored) | `scribe prose\|outline\|chapter\|screenplay\|dialogue\|lore\|revise` | Qwen3.8-27B-Uncensored (mlx-lm, :8081) |
| Vision + camera | `see describe\|ask\|ocr\|compare\|snap` | Qwen3-VL-8B (mlx-vlm, :8082) · imagesnap |
| Image editing | `gen edit in.png "instruction" --fast` | Qwen-Image-Edit 2509 (Q4 GGUF via ComfyUI-GGUF) |
| Stems / karaoke | `stems split\|karaoke song.flac` | Demucs htdemucs (MPS) |
| LoRA training | `lora train --dataset DIR --name NAME` → `gen image --lora NAME` | ostris ai-toolkit (MPS) |

Every `gen` call prints one JSON line (`{"ok":true,"files":[…],"seconds":…}`), waits for an idle
GPU queue, and fails loudly when ComfyUI reports success without writing a file.

## Model decisions by platform

Diffusion, 3D and upscale are ComfyUI on every platform. The **language / voice / vision** engines
are where the platforms diverge, and they are not interchangeable:

| Job | Apple Silicon | Linux (NVIDIA / ROCm) | Windows |
|---|---|---|---|
| Diffusion · 3D · upscale | ComfyUI, MPS | ComfyUI, CUDA/ROCm — backend on `:8189`, shim on `:8188` | ComfyUI, CUDA |
| Writer LLM | `mlx_lm.server` `:8081` · `mlx-community/Qwen3.8-27B-Uncensored-OptiQ-4bit` | `llama-server` `:8000` with a GGUF (e.g. `Qwen3.8-27B-…-Q4_K_P.gguf`) | `llama-server` `:8000`, same GGUF |
| Vision VLM | `mlx_vlm.server` `:8082` · `mlx-community/Qwen3-VL-8B-Instruct-4bit` | `llama-server` with a `Qwen3-VL` GGUF + `mmproj` | `llama-server` + `mmproj` |
| TTS / STT | `mlx-audio` `:8000` (Kokoro, Qwen3-TTS, Whisper turbo) | `speaches` `:8000` (installer default) **or** `voice-tts` `:3200` (Chatterbox) + `voice-stt` `:3201` (faster-whisper) on the V100 deployment | CUDA or CPU path |
| Stems · LoRA | MPS (Demucs, ai-toolkit) | CUDA | CUDA |

Two model *choices* that follow from the hardware:

- **fp8 does not pay on MPS** — it upcasts to bf16 and Qwen-Image-Edit balloons to ~39 GB. Use the
  Q4 GGUF (~13 GB) on Apple Silicon; fp8 is fine on CUDA.
- **VRAM is measured per card, not summed.** The probe uses the largest GPU; `VF_GPU=1` selects
  another index. A 2 GB display card in the box must never receive a model.

Override ComfyUI ports with `VF_COMFY_PORTS` — macOS defaults to `8188`, Linux to `8189,8190`.

## The panel (`control/`)

http://127.0.0.1:8787 — one origin, tabs per modality:

| Tab | Contents |
|---|---|
| Image / Video / Sound / Voice / Write / Vision | run form (same args as the CLI) · jobs list with cancel · gallery with inline preview · camera snap |
| 3D & VR | WebXR room (iframe + full screen) · joint picker · GLB/STL viewer · meshes & prints gallery · "set in room" |
| Models | manifest inventory: present / downloading / missing per model, the forge recommendation for this machine, HF-cached audio models, tool checklist |
| Services | start / stop / restart / logs for ComfyUI, mlx-audio, writer LLM, vision VLM |
| Resources | CPU, GPU (IOAccelerator), memory, swap, disk, top processes · **Unload all models / Stop everything** |

The header is a **per-card strip**: one tile per GPU, showing identity (resolved by UUID, never by
index — enumeration shifts when cards are added), util / VRAM / temp / power, what that card is
running, and the queue attached to it with a live step bar (`step N/M · P%`).

Queue→card attribution is discovered, not configured: the panel finds where each ComfyUI instance
is actually resident and attaches that instance's queue to it, so re-pinning a ComfyUI to another
card moves its queue with it. Two instances are handled (a second card's ComfyUI on `:8190`).

Progress comes from one websocket listener per ComfyUI instance, keyed by `(port, prompt_id)`, so
two instances can never overwrite each other's numbers. ComfyUI **broadcasts** execution events to
every connected client — measured, two different `clientId`s received identical streams — so the
listener does not need to be the client that submitted the prompt.

## Daily use

```bash
stack status | start comfy | start audio | stop comfy | free | logs comfy 100 | panel
gen status                      # which model sets are installed + queue
fetch-models --list             # ✓/✗ per manifest entry;  fetch-models  downloads the ✗
forge-recommend                 # what this machine should fetch;  fetch-models --profile auto  downloads it
voice voices                    # Kokoro voice list
```

Outputs: `output/<kind>/` (gen), `ComfyUI/output/` (raw), `scratch/` (experiments).

## For AI agents (Hermes)

`hermes/` holds the `image_gen` plugin and the skills; `bin/sync-hermes install|export`
moves them in and out of `~/.hermes`. The **`studio`** skill is the entry point and routes
to `studio-video-edit`, `studio-voice`, `studio-3d-print`, `studio-vr`, `studio-game`,
`studio-animation`, `studio-writing`, `studio-vision` and `local-media-stack` (deep 3D reference). Skills are written for a
weaker model: exact commands, exact paths, expected output, measured pitfalls.

## GPU lanes — one source of truth

`config/gpu-lanes.env` is the only place a card is named. Everything else derives from it:
systemd units are pinned by **UUID** through `bin/gpu-lanes apply`, and the tools read the same
file for ports. No code or unit is allowed to use a numeric GPU index.

The port **is** the lane. Port → PCI address is fixed and enforced by `bin/gpu-lanes check`:

| Port | Lane | PCI | Card | Runs |
|---|---|---|---|---|
| `8189` | B | `0000:03:00.0` | V100 B | ComfyUI video + 3D, the lazy writer |
| `8190` | A | `0000:02:00.0` | V100 A | ComfyUI stills, audio + music |
| `8200` | A | `0000:02:00.0` | V100 A | vision VLM |
| `3200` | A | `0000:02:00.0` | V100 A | TTS |
| `3201` | A | `0000:02:00.0` | V100 A | STT |
| — | — | `0000:01:00.0` | GTX 750 Ti | screen + h264_nvenc only, **never a model** |

Chassis note (Precision T5810, board 0HHV7N): **two Gen3 x16 slots** — physical slot 2 and slot 4 —
plus a Gen3 **x8** slot 1. Both V100s sit in the x16 slots and train at x16; the 750 Ti is in the x8
slot, which is why it reports `x8/x16`. Read it yourself:

```bash
bin/gpu-lanes links          # slot, generation, current vs max width
cat /sys/bus/pci/devices/0000:00:02.0/max_link_width   # 16 = the slot is wired x16
```

```bash
bin/gpu-lanes show     # truth table: lane -> card -> service -> what card it is really on
bin/gpu-lanes check    # exit 1 on drift (for scripts / smoke tests)
bin/gpu-lanes which video|stills|A|B   # print the UUID for a lane
bin/gpu-lanes apply --restart          # rewrite the systemd drop-ins from the env file
```

**Why indices are banned here.** Three schemes disagree on this machine, and every outage came
from mixing them:

- `nvidia-smi` order: `0` = 750 Ti, `1` = V100 A, `2` = V100 B
- CUDA order (fastest first): `0` = V100 A, `1` = V100 B, `2` = 750 Ti
- `--cuda-device N`: an ordinal **into `CUDA_VISIBLE_DEVICES`** — and ComfyUI *replaces* that
  variable with `str(args.cuda_device)`, which throws a UUID pin away and re-introduces a bare
  ordinal. That is why `--cuda-device 0` landed on A and `1` on B no matter what was pinned, and
  why the box appeared to work while the reasoning was wrong.

Each service therefore sees exactly **one** card (its UUID) and passes **no** device flag. A job
that needs the other card talks to the other port.

`voice-tts` / `voice-stt` are system units, so their drop-ins need root once:

```bash
sudo mkdir -p /etc/systemd/system/voice-tts.service.d /etc/systemd/system/voice-stt.service.d
printf '[Service]\nEnvironment="CUDA_VISIBLE_DEVICES=%s"\n' "$(bin/gpu-lanes which A)" \
  | sudo tee /etc/systemd/system/voice-tts.service.d/60-lane.conf >/dev/null
printf '[Service]\nEnvironment="CUDA_VISIBLE_DEVICES=%s"\n' "$(bin/gpu-lanes which A)" \
  | sudo tee /etc/systemd/system/voice-stt.service.d/60-lane.conf >/dev/null
sudo systemctl daemon-reload && sudo systemctl restart voice-tts voice-stt
```

## Services

| Service | Port | Where | Protocol |
|---|---|---|---|
| ComfyUI (shim) | 8188 | all — on Linux forwards to the `:8189` backend | `POST /prompt`, `GET /history/{id}`, `GET /queue`, `POST /free`, `ws /ws?clientId=` |
| ComfyUI (backend) | 8189 · 8190 | Linux/Windows; macOS runs ComfyUI on `:8188` directly | same API — the second card's instance is `:8190` |
| mlx-audio | 8000 | **Apple Silicon** | OpenAI-compatible `/v1/audio/speech`, `/v1/audio/transcriptions`; models by HF repo id, loaded on demand |
| writer LLM | 8081 | **Apple Silicon** — `mlx_lm.server` | OpenAI-compatible chat; Qwen3.8-27B-Uncensored 4-bit (`stack start llm`) |
| vision VLM | 8082 | **Apple Silicon** — `mlx_vlm.server` | OpenAI-compatible chat with image parts; Qwen3-VL-8B 4-bit (`stack start vision`) |
| llama-server | 8000 | **Linux / Windows** | OpenAI-compatible chat; GGUF + `mmproj` for vision. Replaces the three MLX services above |
| speaches | 8000 | **Linux** — the installer default | faster-whisper + Kokoro behind the same `/v1/audio/*` routes mlx-audio uses |
| voice-tts | 3200 | **Linux** — V100 deployment | Chatterbox TTS, fp16 |
| voice-stt | 3201 | **Linux** — V100 deployment | faster-whisper, int8 |
| panel | 8787 | all | FastAPI; `PANEL_HOST=0.0.0.0 stack panel` exposes it to the LAN (WebXR still needs localhost/HTTPS) |

The panel's **Services** tab controls whichever engines exist on the machine it runs on.

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

## License

VF Studio is released under the **Apache License, Version 2.0** — the full text is in [LICENSE](LICENSE),
and the canonical version lives at <https://www.apache.org/licenses/LICENSE-2.0>.

- **Covers:** everything in this repository — the installer, CLIs, panel, skills and the model manifest.
- **Does not cover:** model weights. Each one keeps its upstream license (many are research- or
  community-licensed, and `fetch-models` stops rather than guessing when a download needs a login).
  ComfyUI is installed as an upstream clone with its own license, not vendored here.
- **What you make** with the studio is yours; the license puts no claim on generated output.
- Apache 2.0 includes an express patent grant, and asks you to keep the copyright and attribution
  notices if you redistribute.

Copyright 2026 Vybesforge.
