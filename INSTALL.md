# Installing the studio on another Mac

Target: Apple Silicon Mac (M-series), macOS 14+, **32 GB unified memory minimum, 64 GB
recommended** (Flux dev, Qwen-Image-Edit and TRELLIS.2 need the headroom). ~150 GB free
disk for the full model set; ~30 GB for the essentials.

Everything runs locally. Nothing in this repo calls a cloud inference API.

## 1. Clone to the fixed location

```bash
git clone <your-fork-url> ~/media-stack
cd ~/media-stack
```

The path is **not configurable** — the scripts, Hermes skills and panel assume `~/media-stack`.

## 2. Run the installer

```bash
./install.sh                      # base tools, ComfyUI, mlx-audio, tools venv, apps, essential models
./install.sh --all-models         # …plus the full manifest (~136 GB; resumable, re-run if interrupted)
./install.sh --hermes             # …plus Hermes Agent wiring (image_gen plugin + studio skills + config)
./install.sh --no-apps            # skip GUI apps (Blender/Godot/OrcaSlicer/Krita/…)
```

It asks for your password once if Homebrew is missing. Every step is idempotent; re-run
after any failure. Expect 15–30 minutes plus model download time (~18 MB/s on a typical
connection → essentials ≈ 25 min, full set ≈ 2 h).

What you get:

| Service / tool | Where |
|---|---|
| Studio panel (tabs, progress, previews, inventory) | http://127.0.0.1:8787 — `stack panel` |
| ComfyUI (image, video, 3D, SFX, music) | :8188 — `stack start comfy` |
| mlx-audio (TTS, STT, voice clone) | :8000 — `stack start audio` |
| CLIs on PATH | `gen`, `voice`, `vid`, `stack`, `fetch-models`, `blender` |
| Toolkits | `tools/print/` (CAD→STL→G-code), `tools/vr/` (GLB optimize), `tools/video/` (VSE, SRT) |
| Godot OpenXR room | `vr-godot/` (`Godot --path ~/media-stack/vr-godot --xr-mode off`) |

## 3. Verify

```bash
stack status
gen status                                   # every model set true/false + queue
gen image "a brass compass on an old map"   # -> output/image/*.png in ~30 s
voice say "hello from the studio"           # -> wav path printed
fetch-models --list                          # ✓/✗ per model
```

Open http://127.0.0.1:8787 → Image tab → Generate. The header bar shows live step progress;
the result appears in the gallery.

## 4. Models

`models/manifest.json` is the single source of truth (id, path, URL, size, role).
`fetch-models` downloads what is missing, sequentially and resumably (`.part` files),
`fetch-models <id> …` fetches specific ones. Add a model = add a manifest entry.

Essentials (installer default): Z-Image-Turbo (+Qwen3-4B encoder, VAE), RealESRGAN,
4x-UltraSharp, Stable Audio Open 1.0 (+t5-base), TRELLIS.2 (+DINOv3, BiRefNet).
Full set adds: Flux dev fp8, FLUX.2 klein 4B, Z-Image ControlNet Union, Qwen-Image-Edit 2509,
Wan 2.2 TI2V 5B, Stable Audio 3 medium, ACE-Step 1.5, SeedVR2.

Voice models (Kokoro, Qwen3-TTS, Whisper) download into `~/.cache/huggingface` on first use.

## 5. Hermes Agent (optional)

`./install.sh --hermes` (or `bin/sync-hermes install`) copies `hermes/plugins/image_gen/comfyui`
and `hermes/skills/*` into `~/.hermes` and sets `image_gen.provider=comfyui`,
`tts`/`stt` → mlx-audio. The `studio` skill is the agent's entry point; it routes to
`studio-video-edit`, `studio-voice`, `studio-3d-print`, `studio-vr`, `local-media-stack`.

Before committing changes made to skills/plugin on a machine: `bin/sync-hermes export`.

## 6. Known hardware notes

- Timings in `hermes/skills/studio/studio/references/benchmarks.md` are from an M3 Max 40-core
  GPU. An M1/M2 Pro will be ~2–3× slower; 32 GB machines should skip Flux dev and run
  Qwen-Image-Edit alone.
- Never benchmark while `fetch-models` is writing — disk contention inflates timings 2–3×.
- WebXR in the panel's room only works on `localhost`/HTTPS; Godot's Windows export is for
  a SteamVR PC (copy `scratch/vr-test/export/win/VRGodotRoom.exe` over).
- OrcaSlicer `generic` preset uses a 250 mm Marlin bed; override `printable-area` for yours.
  The `bambu` preset targets P1S/X1C 0.4 mm, Bambu PLA Basic, 0.20 mm.

## Layout

```
install.sh              this installer          INSTALL.md   this file
bin/                    stack · fetch-models · sync-hermes · blender wrapper · restore-known-good
control/                panel.py + studio.py + studio.html  (FastAPI, :8787)
tools/comfy/gen         image / control / upscale / video / sfx / music
tools/voice/voice       say / voices / clone / transcribe / enhance
tools/video/            vid · vse_build.py · transcribe_srt.py
tools/print/            cad_examples/ · meshcheck.py · slice
tools/vr/               gltf · optimize_glb.sh
vr/                     WebXR room, joint picker, GLB/STL viewer (Three.js vendored)
vr-godot/               Godot 4 OpenXR project
models/manifest.json    model list              hermes/      plugin + skills for Hermes Agent
scratch/                experiments (gitignored binaries)   STATE.md   project handoff notes
```
