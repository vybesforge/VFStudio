# media-stack

Local generation stack on this Mac (M3 Max, 64 GB unified, 40-core GPU).
Everything here runs offline on the GPU. Hermes routes to it.

```
~/media-stack/
├── bin/stack                 # CLI: start/stop/restart/status/logs/panel
├── control/panel.py          # web panel  → http://127.0.0.1:8787
├── audio/.venv               # mlx-audio  → :8000  (TTS, STT, music, SFX)
├── ComfyUI/.venv             # ComfyUI    → :8188  (image, video)
├── ComfyUI/models/checkpoints
├── logs/                     # per-service logs
├── run/                      # pid files
└── scratch/                  # test output
```

## Daily use

```bash
stack panel          # open the control panel (starts it if needed)
stack status         # what's running + which models are installed
stack start audio    # mlx-audio  on :8000
stack start comfy    # ComfyUI    on :8188
stack stop comfy     # free the unified memory again
stack restart audio
stack logs comfy 100 # tail 100 lines
stack free           # unload ComfyUI models, release VRAM
stack music "jazz trio, brushed drums"   # text -> music (local)
stack vr             # open the panel on the VR Room tab
```

The panel at **http://127.0.0.1:8787** is the single origin for everything:

| Tab | What it does |
|---|---|
| Services | start/stop/restart, per-service logs, installed models, Free VRAM |
| VR Room | the WebXR asset test room, served from `/vr/` |
| Assets | every GLB and generated image, with tri counts and a "Set in room" button |
| Resources | live CPU, GPU, memory, swap, disk and per-process RSS |

## VR asset test room

`~/media-stack/vr/` is a self-contained WebXR scene (Three.js vendored locally —
no CDN, no external requests). It loads `pig.glb` from the same folder, sits it
on the floor and centres it whatever units the model uses, and gives you a 1 m
grid plus a 1.8 m height reference so scale is obvious in headset.

Controls: wireframe, rotate, grid on/off, brightness.

**Testing on the Windows / RTX 4080 box:**

1. Either copy the `vr/` folder to the Windows box, **or** serve it from the Mac
   over the LAN:
   ```bash
   PANEL_HOST=0.0.0.0 stack panel   # then browse to http://<mac-ip>:8787 from Windows
   ```
   Loopback-only by default; opt in to LAN exposure deliberately.
2. Open it in **Chrome or Edge** — Firefox has no WebXR on Windows.
3. Click **Open full screen**, then **Enter VR**. SteamVR must be running;
   Chrome bridges to it through OpenXR.
4. The embedded iframe is for desktop inspection only — WebXR in an iframe is
   unreliable, so use the full-screen button for anything real.

Drop any `.glb` beside `index.html` (rename to `pig.glb`, or edit the loader
line) and it appears in the room.


## Image → 3D (all local)

ComfyUI ships Hunyuan3D 2.1 natively. Weights: `Comfy-Org/Hunyuan-3D-2.1` →
`hunyuan_3d_v2.1.safetensors` in `models/checkpoints` (7.4 GB, all-in-one:
MODEL + CLIP_VISION + VAE).

```bash
# bare geometry, ~146 s
python scratch/make_pig_3d.py reference.png

# decimate -> unwrap -> bake the reference as base colour, ~233 s
python scratch/make_pig_3d.py --decimate 120000 \
  --texture reference.png reference.png

# 4 consistent views (front right back left)
python scratch/make_pig_3d.py front.png right.png back.png left.png
```

Output lands in `ComfyUI/output/3d/` and is copied to `vr/pig.glb`.

**Hard-won limits:**

- ComfyUI only rescans `models/checkpoints` **at startup** — restart after
  downloading weights.
- `UnwrapMesh` on a dense mesh **OOMs the server**: a 256-octree pig produced
  381,878 UV charts and ComfyUI died at 78% of packing. Decimate first —
  120k faces → 69,751 charts → fine.
- `ApplyTextureToMesh` **requires UVs** (`mesh has no UVs`), so unwrap is
  mandatory before texturing; there's no shortcut.
- Native Hunyuan3D is **geometry only** — no texture stage. Texturing here is a
  base-colour projection from your reference, not true multi-view PBR paint.
- Output is normalised to ~[-1, 1] units; scale in the scene.

## Blender repair pass

ComfyUI's GLB has no `NORMAL` attribute and a near-empty projected texture, so it
renders as a faceted blank toy. `scratch/blender_repair.py` fixes both:

```bash
~/media-stack/bin/blender -b --python scratch/blender_repair.py -- \
  vr/pig.glb vr/pig_clean.glb reference.png 120000 2048
```

Clear split normals → weld → Smart UV Project → triplanar BOX projection →
bake base colour + AO at 2048 → smooth shade → export.

```bash
# compare two assets from the same camera
~/media-stack/bin/blender -b --python scratch/render_asset.py -- \
  vr/pig_clean.glb /abs/path/render.png 900
```

Never symlink Blender into PATH — use the wrapper in `bin/blender`, which execs
the binary inside the .app and unsets `PYTHONHOME`.

## Services

| Service | Port | What it does |
|---|---|---|
| mlx-audio | 8000 | OpenAI-compatible `/v1/audio/speech` (TTS), `/v1/audio/transcriptions` (STT), music + SFX models. Models load on demand and stay warm. |
| ComfyUI | 8188 | Diffusion image/video generation. `POST /prompt`, `GET /history/{id}`, `GET /view`. |

### mlx-audio models

Models are chosen per request by HF repo id — no server restart needed.

| Kind | Repo | Notes |
|---|---|---|
| TTS | `mlx-community/Kokoro-82M-bf16` | default, 8 languages, ~130 ms warm |
| TTS | `mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-bf16` | voice design, multilingual |
| TTS | `mlx-community/chatterbox-multilingual-v3` | expressive, 23 languages |
| STT | `mlx-community/whisper-large-v3-turbo-asr-fp16` | default, 99 languages |
| STT | `mlx-community/parakeet-tdt-0.6b-v3` | faster, EN + 25 EU |
| Music | `mlx-community/MiniMax-Music3-8bit` | full songs with lyrics, 44.1 kHz stereo |

First call for a model pays a load cost (Kokoro ~45 s, Whisper ~18 s); after
that it stays resident.

CLI for one-offs (bypasses the server):

```bash
~/media-stack/audio/.venv/bin/mlx_audio.tts.generate \
  --model mlx-community/Kokoro-82M-bf16 --text "hello" --voice af_heart --play
```

## Hermes routing

`~/.hermes/config.yaml`:

```yaml
tts:
  provider: openai
  openai: {base_url: http://127.0.0.1:8000/v1, api_key: not-needed,
           model: mlx-community/Kokoro-82M-bf16, voice: af_heart}
stt:
  enabled: true
  provider: openai
  openai: {base_url: http://127.0.0.1:8000/v1,
           model: mlx-community/whisper-large-v3-turbo-asr-fp16}
image_gen:
  provider: comfyui
```

Image gen goes through the plugin at
`~/.hermes/plugins/image_gen/comfyui/` — it reads
`ComfyUI/models/checkpoints` live, so any checkpoint you drop in becomes a
selectable model in `hermes tools`.

**If a service is stopped, the corresponding tool fails with a clear
"not running" error** rather than silently falling back to a cloud provider.

## Adding models

Images/video — drop into the right folder, no config edit:

```bash
cd ~/media-stack/ComfyUI/models
# checkpoints/  flux, sdxl, sd15
# loras/        any LoRA
# vae/          standalone VAE
# clip/         text encoders
# unet/         split-flux bundles
```

Audio — nothing to do; the server pulls any HF repo id on first request.

## Notes

- 64 GB unified means Flux fp16/GGUF-Q8 and SDXL fit fully; video models
  (Wan/AnimateDiff) fit but are slow — expect minutes per clip, not seconds.
- Only one ComfyUI job runs at a time. Queue extra prompts in the UI.
- `stack free` is the fast way to hand memory back to the OS.
- ComfyUI's own outputs also land in `ComfyUI/output/`; the Hermes plugin
  copies each result into `~/.hermes/cache/generated/images/`.
