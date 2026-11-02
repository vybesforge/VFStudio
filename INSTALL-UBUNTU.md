# VF Studio on Ubuntu (NVIDIA)

The stack was built and measured on an M3 Max Mac. It ports to Ubuntu, but **three of the
five services are Apple-only (MLX)** and need CUDA stand-ins. Everything else — ComfyUI, the
`gen`/`vid`/`slice`/`stems`/`lora` CLIs, the panel, Blender/Godot/OrcaSlicer tooling, the
skills — is plain Python + ffmpeg and runs unchanged.

> Status: **written from the code, not yet executed on an Ubuntu box.** Dylan's Precision 5810
> (V100 32 GB + RTX 2060) and the RTX 4080 box are the targets. First person to run it: fix this
> file where reality differs and commit it. Timings quoted in the skills are Mac numbers.

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

Memory model is different too: on the Mac everything shared one 64 GB pool; on a GPU box you are
bound by **VRAM**. V100 32 GB: Z-Image (bf16 ≈ 12 GB) + text encoder fits; Flux dev fp8 fits;
Wan 2.2 5B fits; Qwen-Image-Edit 2509 fp8 (~20 GB) fits alone; a 27B writer at Q4 (~17 GB) does
**not** coexist with ComfyUI on one 32 GB card — run it on the 2060 (no: 6 GB — too small) or
time-share with the panel's *Unload all*. RTX 4080 16 GB: use the fp8/4-bit variants and a
≤14B writer (Q4 ≈ 9 GB).

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

Models: identical manifest.
```bash
bin/fetch-models --list
bin/fetch-models            # ~25 GB essentials (Z-Image, klein, Wan 2.2 5B, SAO, ACE-Step, upscalers)
bin/fetch-models --all      # ~136 GB everything incl. Qwen-Image-Edit 2509, Flux dev, Stable Audio 3
```

## 3. Tools venv + CLIs (unchanged)

```bash
uv venv --python 3.12 tools/.venv
uv pip install --python tools/.venv/bin/python build123d trimesh pygltflib numpy-stl moviepy pedalboard librosa soundfile pillow imageio-ffmpeg requests websocket-client scipy
mkdir -p ~/.local/bin
for c in tools/comfy/gen tools/voice/voice tools/video/vid tools/llm/scribe tools/vision/see tools/print/slice tools/vr/gltf tools/audio/stems tools/train/lora bin/stack bin/fetch-models; do ln -sf "$PWD/$c" ~/.local/bin/$(basename "$c"); done
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

```bash
stack status
gen image "a brass compass on an old map" --model klein --seed 1      # expect ~5–8 s on a V100, output/image/klein_*.png
voice say "ok" --out /tmp/ok.wav && voice transcribe /tmp/ok.wav
scribe prose "test" --words 60
see describe output/image/klein_00001_.png
```

## Known gaps on Linux (honest list)
- Voice cloning server is not packaged — §5 describes the route, nobody has run it.
- `control/status.py` GPU stats are macOS-only until the `nvidia-smi` fallback is added.
- `bin/stack` service definitions for `llm`/`vision` reference `mlx_lm.server`/`mlx_vlm.server`; swap to `llama-server` lines.
- Skills quote Mac timings; CUDA numbers will be faster for diffusion, similar or faster for LLMs.
- No Rosetta-style issues, but AppImages need FUSE (`sudo apt install libfuse2`).
