# CUDA and ROCm stand-ins

Start with `python3 tools/forge/install.py`. It probes the machine and writes `run/forge-engines.json`. This file is the detail for a discrete GPU: ComfyUI on CUDA or ROCm, speaches for voice, llama-server for the writer and for vision. MLX weights are not loaded here.

The stack was first exercised on Apple Silicon. It ports to Linux, but **three of the
five services are Apple-only (MLX)** and need CUDA stand-ins. Everything else — ComfyUI, the
`gen`/`vid`/`slice`/`stems`/`lora` CLIs, the panel, Blender/Godot/OrcaSlicer tooling, the
skills — is plain Python + ffmpeg and runs unchanged.

> Status: **written from the code, not yet executed on an Ubuntu box.** First person to run it: fix this
> file where reality differs and commit it. Timings quoted in the skills are from one Apple Silicon machine.

## What changes

| Piece | macOS (as built) | Ubuntu replacement | Why |
|---|---|---|---|
| Package manager | Homebrew | `apt` (+ a few `pipx`/`uv` installs) | — |
| ComfyUI backend | PyTorch **MPS** | PyTorch **CUDA** (`cu124`+ wheels) | same ComfyUI, same models, same `gen` |
| TTS / STT / clone (`:8000`) | `mlx-audio` server | **`speaches`** (faster-whisper + Kokoro, OpenAI-compatible) | `voice` only needs `/v1/audio/speech` + `/v1/audio/transcriptions` |
| Voice clone model | Qwen3-TTS (MLX) | Kokoro has no cloning → run **Qwen3-TTS PyTorch** or **Chatterbox** separately (see §5) | MLX weights don't load in torch |
| Writer LLM (`:8081`) | `mlx_lm.server` | **`llama-server`** (llama.cpp, CUDA) with a GGUF | OpenAI-compatible; `scribe` reads `LLM_HOST` |
| Vision VLM (`:8082`) | `mlx_vlm.server` | **`llama-server`** with Qwen3-VL GGUF + mmproj | OpenAI-compatible image parts; `see` reads `VLM_HOST`/`VLM_MODEL` |
| Camera | `imagesnap` | `ffmpeg -f v4l2` (already in `see snap`, `--device /dev/video0`) | — |
| GUI apps | brew casks | `apt`/`snap`/`flatpak`/upstream tarballs | Blender/Godot/OrcaSlicer/Krita/Inkscape/Audacity/OpenSCAD/MeshLab all ship Linux builds; **OpenToonz runs natively** (no Tahoma2D detour needed) |
| 3D print slicing | OrcaSlicer.app CLI | OrcaSlicer AppImage `--slice` | `tools/print/slice` finds the binary via `$ORCA_BIN` |
| Demucs / LoRA training | `--device mps` | `--device cuda` | the CLIs auto-pick CUDA when present |
| Service manager | `bin/stack` (launchd-free, works as is) | same; optional systemd units in §8 | — |

On a discrete GPU you are bound by **VRAM on the largest card**, not the sum of cards and not
the Mac's unified-memory pool. Run `bin/forge-recommend` before fetching. It reads this machine
and applies the same limits everywhere:

| Detected limit | What `--profile auto` keeps | What it skips |
|---|---|---|
| NVIDIA/AMD ≥ 24 GB | fp8 edit path, Flux dev fp8, Wan 2.2 5B, HunyuanVideo 1.5 | the Qwen GGUF (the fp8 file fits), MLX repos |
| NVIDIA/AMD 16 GB (a driver that reports ~16376 MiB still counts as 16) | GGUF edit path, Flux dev fp8 (tight), Wan 2.2 5B | fp8 edit (~24 GB), HunyuanVideo (~20 GB), MLX repos |
| NVIDIA/AMD 8 GB | FLUX.2 klein, small SFX, classical upscalers | Z-Image, Wan, Flux dev |
| Apple unified ≥ 48 GB | MLX voice / vision / writer, Qwen GGUF, Flux dev | Qwen fp8 (it upcasts) |
| Apple unified under 48 GB | GGUF edit, Z-Image if memory allows | Flux dev, HunyuanVideo, the 27B writer |
| no GPU | RealESRGAN and 4x-UltraSharp | every diffusion model |

A 27B Q4 writer is about 17 GB and time-shares a card that large (`stack free` first). Under 24 GB
VRAM, use a ≤14B Q4 GGUF via llama-server. Text encoders offload on cards under 24 GB. MLX weight
files are not the CUDA or ROCm build.

## 1. Base packages

```bash
sudo apt update
sudo apt install -y git git-lfs ffmpeg sox build-essential python3-venv curl \
  v4l-utils libgl1 libglib2.0-0 cmake pkg-config
curl -LsSf https://astral.sh/uv/install.sh | sh          # uv → ~/.local/bin/uv
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && sudo apt install -y nodejs
npm i -g @gltf-transform/cli
# NVIDIA: driver ≥ 550 and CUDA runtime come with the driver; verify
nvidia-smi
```

## 2. Repo + ComfyUI (CUDA)

```bash
git clone https://github.com/vybesforge/VFStudio.git ~/media-stack && cd ~/media-stack
git clone https://github.com/comfyanonymous/ComfyUI && (cd ComfyUI && git checkout "$(cat ../COMFYUI_COMMIT)")
uv venv --python 3.12 ComfyUI/.venv
uv pip install --python ComfyUI/.venv/bin/python torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
uv pip install --python ComfyUI/.venv/bin/python -r ComfyUI/requirements.txt
uv pip install --python ComfyUI/.venv/bin/python comfyui-workflow-templates   # gen reads node signatures from these
ComfyUI/.venv/bin/python -c "import torch;print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

`bin/stack` starts ComfyUI with `--listen 127.0.0.1 --port 8188`; remove any `--force-fp16`/MPS flags
if you find them in `bin/stack` (grep `mps`). For ≤16 GB cards add `--lowvram` or `--fp8_e4m3fn-unet`.

Models: the same manifest. Probe first, then fetch the profile for this GPU.
```bash
bin/forge-recommend                  # or: python3 tools/forge/recommend.py
bin/forge-recommend --dry-run        # the probe never downloads; this flag is accepted anyway
bin/fetch-models --dry-run --profile auto
bin/fetch-models --profile auto      # essentials + quality that fit the largest GPU and the free disk
bin/fetch-models --list              # ✓/✗ per manifest id
```
`fetch-models --profile essentials` is the small set that fits (Z-Image, upscalers, Stable Audio
Open, and TRELLIS.2 when VRAM or unified memory allows). `--profile full` adds optional files
such as Stable Audio 3 medium. There is no `--all` flag; fetching every id regardless of VRAM is
`bin/fetch-models` with no profile. Do that only when you mean to.

Windows: `python tools/forge/recommend.py` runs as-is. `bin/fetch-models` is bash — Git Bash or
WSL. ComfyUI itself is the CUDA install above, pointed at the same `models/` tree. AMD uses the
same VRAM rules with a ROCm PyTorch build; the stack was measured on CUDA and Apple Silicon, so
smoke-test klein before fetching the quality tier.

## 3. Tools venv + CLIs (unchanged)

```bash
uv venv --python 3.12 tools/.venv
uv pip install --python tools/.venv/bin/python build123d trimesh pygltflib numpy-stl moviepy pedalboard librosa soundfile pillow imageio-ffmpeg requests websocket-client scipy
mkdir -p ~/.local/bin
for c in tools/comfy/gen tools/voice/voice tools/video/vid tools/llm/scribe tools/vision/see tools/print/slice tools/vr/gltf tools/audio/stems tools/train/lora bin/stack bin/fetch-models bin/forge-recommend; do ln -sf "$PWD/$c" ~/.local/bin/$(basename "$c"); done
```
The CLIs have `#!/usr/bin/env` or venv shebangs pointing at `tools/.venv`/`audio/.venv`; if a
shebang hard-codes a Mac path it will fail with "bad interpreter" — fix the shebang, that is a bug
in the repo, please commit the fix.

## 4. Panel (`:8787`)

The panel runs in `audio/.venv` on the Mac. On Ubuntu create it the same way but with the
speaches server instead of mlx-audio:

```bash
uv venv --python 3.12 audio/.venv
uv pip install --python audio/.venv/bin/python fastapi uvicorn websocket-client python-multipart psutil
bin/stack panel     # http://127.0.0.1:8787
```
`control/status.py` reads GPU utilisation through `ioreg` on macOS; on Linux it should fall back to
`nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv` — if the Resources tab shows GPU
"n/a", that fallback is the thing to add. The *Unload all* button calls ComfyUI `/free` and
`stack stop llm vision`, which work identically.

## 5. Voice (`:8000`) — speaches instead of mlx-audio

```bash
uv pip install --python audio/.venv/bin/python "speaches[ui]"          # or: docker run ghcr.io/speaches-ai/speaches:latest-cuda
# start on 8000 so `voice` needs no change:
UVICORN_HOST=127.0.0.1 UVICORN_PORT=8000 audio/.venv/bin/speaches &
voice say "hello from ubuntu" --voice af_heart         # Kokoro via /v1/audio/speech
voice transcribe some.wav                              # faster-whisper via /v1/audio/transcriptions
```
Model ids differ (speaches uses `Systran/faster-whisper-large-v3`, `speaches-ai/Kokoro-82M-v1.0-ONNX`);
set them with `WHISPER_MODEL=... TTS_MODEL=...` env vars read by `voice` (see `tools/voice/voice`
top of file — the `env = os.environ.get(name.upper())` hook). Voice cloning: speaches has none.
Options, both CUDA: **Chatterbox** (`pip install chatterbox-tts`, ~4 GB VRAM, no transcript needed)
or **Qwen3-TTS** PyTorch release. Wrap either as an OpenAI-style `/v1/audio/speech` that accepts
`ref_audio`/`ref_text`, run it on another port, and point `voice clone` at it with
`VOICE_SERVER=http://127.0.0.1:8001 VOICE_CLONE_MODEL=chatterbox`. Mark this *untested*.

## 6. Writer LLM (`:8081`) and vision VLM (`:8082`) — llama.cpp

```bash
# llama.cpp with CUDA (prebuilt releases exist; or build):
git clone https://github.com/ggml-org/llama.cpp && cd llama.cpp && cmake -B build -DGGML_CUDA=ON && cmake --build build -j && cd ..
# writer — pick a GGUF of the same family (Q4_K_M ≈ 17 GB for 27B; use a 14B on 16 GB cards):
HF_HUB_DISABLE_XET=1 uvx --from huggingface_hub hf download <GGUF repo of Qwen3.x-27B-Uncensored> --include "*Q4_K_M*" --local-dir ~/models/writer
llama.cpp/build/bin/llama-server -m ~/models/writer/*.gguf -ngl 99 -c 32768 --port 8081 --host 127.0.0.1 &
# vision — Qwen3-VL GGUF + its mmproj file:
llama.cpp/build/bin/llama-server -m ~/models/qwen3-vl-8b/*Q4_K_M.gguf --mmproj ~/models/qwen3-vl-8b/mmproj*.gguf -ngl 99 --port 8082 &
LLM_HOST=http://127.0.0.1:8081 scribe status
VLM_HOST=http://127.0.0.1:8082 VLM_MODEL=qwen3-vl see ask photo.jpg "what is this"
```
`scribe` disables Qwen thinking with `chat_template_kwargs.enable_thinking=false`; llama-server
honours the same field. Put the two `export LLM_HOST=… VLM_HOST=…` lines in `~/.bashrc` so the
panel (which shells out to the CLIs) sees them, and edit `bin/stack`'s `llm`/`vision` service
commands to launch `llama-server` instead of `mlx_lm.server` (one line each).

## 7. GUI apps

```bash
sudo snap install blender --classic            # or the tarball from blender.org (5.x)
sudo snap install godot-4 --classic || flatpak install org.godotengine.Godot
sudo apt install -y krita inkscape audacity openscad meshlab opentoonz
# OrcaSlicer: AppImage from github.com/SoftFever/OrcaSlicer/releases
chmod +x OrcaSlicer*.AppImage && mv OrcaSlicer*.AppImage ~/.local/bin/orcaslicer
export ORCA_BIN=~/.local/bin/orcaslicer        # tools/print/slice uses this
```
Godot export templates: `~/.local/share/godot/export_templates/<version>/` (the installer's
`tpz_partial.py` trick works the same). Blender headless scripts (`tools/anim/*.py`,
`tools/video/vse_build.py`) are platform-neutral; set `BLENDER=/snap/bin/blender` if `blender`
is not on PATH.

## 8. Autostart (systemd user units, optional)

```ini
# ~/.config/systemd/user/vf-panel.service
[Unit]
Description=VF Studio panel
After=network.target
[Service]
WorkingDirectory=%h/media-stack
ExecStart=%h/media-stack/bin/stack panel --foreground
Restart=on-failure
[Install]
WantedBy=default.target
```
`systemctl --user enable --now vf-panel`. ComfyUI/LLM/VLM stay on-demand from the panel so one
GPU is not held by idle weights.

## 9. Smoke test

`forge-recommend` prints a `gen` line for whatever image model it kept. When klein is in the set:

```bash
stack status
gen image "a brass compass on an old map" --model klein --seed 1      # output/image/klein_*.png
voice say "ok" --out /tmp/ok.wav && voice transcribe /tmp/ok.wav
scribe prose "test" --words 60
see describe output/image/klein_00001_.png
```

## Known gaps on Linux (honest list)
- Voice cloning server is not packaged — §5 describes the route, nobody has run it.
- `control/status.py` live GPU utilisation is still macOS-only (`ioreg`). `bin/forge-recommend` and the Models tab do probe `nvidia-smi` for name, VRAM, and driver; the Resources tab's percent-busy figure does not, yet.
- `bin/stack` service definitions for `llm`/`vision` reference `mlx_lm.server`/`mlx_vlm.server`; swap to `llama-server` lines.
- Skills quote Mac timings; CUDA numbers will be faster for diffusion, similar or faster for LLMs.
- No Rosetta-style issues, but AppImages need FUSE (`sudo apt install libfuse2`).
