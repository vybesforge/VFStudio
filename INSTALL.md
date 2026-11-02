# Installing the studio on another Mac

> Linux / NVIDIA box instead? See [INSTALL-UBUNTU.md](INSTALL-UBUNTU.md).

Target: Apple Silicon Mac (M-series), macOS 14+, **32 GB unified memory minimum, 64 GB
recommended** (Flux dev, Qwen-Image-Edit and TRELLIS.2 need the headroom). About 40 GB free
for the essentials profile (~36 GB of weights); about 230 GB if you download every ComfyUI
file plus the MLX repos. `bin/forge-recommend` trims that to what this Mac can hold.

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
| CLIs on PATH | `gen`, `voice`, `vid`, `scribe`, `see`, `stack`, `fetch-models`, `forge-recommend`, `blender` |
| Writer LLM / vision VLM | :8081 / :8082 — `stack start llm` / `stack start vision` (models in `models/hf-models.txt`) |
| Game + animation | `game/templates/godot-{2d,3d}`, `tools/anim/` |
| Toolkits | `tools/print/` (CAD→STL→G-code), `tools/vr/` (GLB optimize), `tools/video/` (VSE, SRT) |
| Godot OpenXR room | `vr-godot/` (`Godot --path ~/media-stack/vr-godot --xr-mode off`) |

## 3. Verify

```bash
bin/forge-recommend                          # what this Mac should fetch, and why
stack status
gen status                                   # every model set true/false + queue
gen image "a brass compass on an old map"   # -> output/image/*.png in ~30 s
voice say "hello from the studio"           # -> wav path printed
fetch-models --list                          # ✓/✗ per model
```

Open http://127.0.0.1:8787 → Image tab → Generate. The header bar shows live step progress;
the result appears in the gallery.

## 4. Models

`models/manifest.json` is the single source of truth (id, path, URL, size, role, and a `fit`
block the recommender reads). `fetch-models` downloads what is missing, sequentially and
resumably (`.part` files). `fetch-models <id> …` fetches specific ones. Add a model = add a
manifest entry and a `fit` block; do not rename an existing id.

```bash
bin/forge-recommend                     # detected OS / CPU / RAM / GPUs / free disk + tiers
bin/forge-recommend --ids               # ids only, for scripts
fetch-models --profile essentials       # smallest useful set
fetch-models --profile auto             # essentials + quality
fetch-models --profile full             # auto, plus optional heavy files that still fit
fetch-models --dry-run --profile auto   # print the plan, download nothing
```

On a 64 GB Mac the essentials profile is Z-Image-Turbo (+Qwen3-4B encoder, VAE), RealESRGAN,
4x-UltraSharp, Stable Audio Open 1.0 (+t5-base), and TRELLIS.2 (+DINOv3, BiRefNet). Quality
adds FLUX.2 klein, Flux dev fp8 (slow; fp8 upcasts), the Qwen-Image-Edit **Q4 GGUF** (not the
fp8 file), Wan 2.2 5B, HunyuanVideo 1.5, ACE-Step, SeedVR2, and the small SFX model. A 32 GB
Mac skips Flux dev, HunyuanVideo, and the 27B writer.

MLX repos (Kokoro, Parakeet, Qwen3-TTS, Qwen3-VL, the 27B writer) are `hf_models` in the same
manifest. The installer downloads them with `HF_HUB_DISABLE_XET=1`; the 27B writer only with
`--all-models`. A `models/hf-models.txt` file, if you add one, overrides that list. XET is
disabled on purpose — with it on, downloads completed with no weights on disk.

If a URL returns 401/403, run `huggingface-cli login` or export `HF_TOKEN` (or
`HUGGING_FACE_HUB_TOKEN`). `fetch-models` forwards it as a bearer header. Never commit the token.

## 5. Hermes Agent (optional)

`./install.sh --hermes` (or `bin/sync-hermes install`) copies `hermes/plugins/image_gen/comfyui`
and `hermes/skills/*` into `~/.hermes` and sets `image_gen.provider=comfyui`,
`tts`/`stt` → mlx-audio. The `studio` skill is the agent's entry point; it routes to
`studio-video-edit`, `studio-voice`, `studio-3d-print`, `studio-vr`, `local-media-stack`.

Before committing changes made to skills/plugin on a machine: `bin/sync-hermes export`.

## 6. Known hardware notes

- Timings in `hermes/skills/studio/studio/references/benchmarks.md` are from an M3 Max 40-core
  GPU. An M1/M2 Pro will be ~2–3× slower; 32 GB machines should skip Flux dev and run
  Qwen-Image-Edit alone. `bin/forge-recommend` applies that split (GGUF edit path, no fp8,
  no 27B writer under 48 GB unified).
- Never benchmark while `fetch-models` is writing — disk contention inflates timings 2–3×.
- WebXR in the panel's room only works on `localhost`/HTTPS; Godot's Windows export is for
  a SteamVR PC (copy `scratch/vr-test/export/win/VRGodotRoom.exe` over).
- OrcaSlicer `generic` preset uses a 250 mm Marlin bed; override `printable-area` for yours.
  The `bambu` preset targets P1S/X1C 0.4 mm, Bambu PLA Basic, 0.20 mm.

## Layout

```
install.sh              this installer          INSTALL.md   this file
bin/                    stack · fetch-models · forge-recommend · sync-hermes · blender wrapper · restore-known-good
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
