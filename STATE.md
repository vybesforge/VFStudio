# Project state — read this first

Last updated: 2026-10-31 (desktop session)

Handoff note so any surface (desktop, Telegram, another bot) can pick up where the
last one stopped. Update this file at the end of significant work.

## What exists

`~/media-stack` — local generation stack, all on-device, no cloud APIs for creation.

| Service | Port | Status |
|---|---|---|
| ComfyUI | 8188 | up — Flux, SDXL, Hunyuan3D, TRELLIS 2 |
| mlx-audio | 8000 | up — TTS/STT/music, OpenAI-compatible |
| panel | 8787 | up — tabs: Services / VR Room / Assets / Resources |

Routing already wired into Hermes: `image_gen.provider: comfyui`, `tts`/`stt`
→ mlx-audio. Verified working.

## VR project (current focus)

Goal: realistic pig asset + test room, playable on the Windows RTX 4080 box via
SteamVR.

- `vr/index.html` — WebXR asset test room, Three.js vendored (offline, zero
  external requests). Loads `vr/pig.glb`. 1 m grid + 1.8 m scale reference.
- **Best asset: `vr/pig_clean.glb`** — 94,298 tris, smooth, textured.
  = Hunyuan3D geometry + Blender repair (clean UV atlas, triplanar + AO bake at
  2048, split normals cleared, smooth shading).
- `vr/pig.glb` — raw Hunyuan3D output: no NORMAL attribute, near-blank texture.
  Kept only for comparison.
- `vr/pig_trellis.glb` — TRELLIS 2: good smooth geometry (140k tris), but the
  texture stage produced corrupted colours (abstract stripes, wrong hues).
  Same failure on the vertex-colour path (`--vcol`), so the fault is the texture
  stage, not the bake.
- `vr/pig_trellis_vcol.glb` — vertex-colour variant, same corruption.

## TRELLIS 2 finding (settled — do not re-litigate)

Six variants tested; **geometry is good, the texture stage produces degenerate
output on this setup.** Every attempt yielded flat uniform colour:

| variant | result |
|---|---|
| UV-bake path (slot 0) | abstract stripes / wrong hues |
| `--vcol` vertex colours | same corruption |
| Dylan's refine pass (`pig_trellis_v2`) | flat grey-green |
| + `RescaleCFG` 0.5/0.7 | flat grey |
| `TEXSLOT=1`, `TEXSLOT=2` | near-black / near-white |

`BakeTextureFromVoxel` emits 3 images; **none** of the three slots carries usable
colour — so the fault is upstream in the texture diffusion stage, not in slot
selection, UVs, or the bake. The graph now matches the reference template
(refine pass + CFG rescale), so wiring is no longer the likely cause.

**Remaining hypothesis:** the `trellis_2_int8_convrot` quantized UNET produces
garbage in the texture stage on MPS. Untested next step is the bf16 model
(`diffusion_models/trellis_2_bf16.safetensors`, 9.6 GB, not downloaded).

**Decision:** ship the Hunyuan + Blender asset. TRELLIS geometry is smoother, but
without usable texture it is not the better deliverable.

## Next steps (unstarted)

1. ~~TRELLIS texture fix~~ — attempted six ways, see the finding above. Only
   untested lever is the bf16 UNET (9.6 GB download).
2. Occupancy/lock so concurrent jobs on the 64 GB machine don't OOM: **done** —
   `/api/comfy/job` + an occupancy line in the panel, and generation scripts wait
   for an idle queue (`--now` overrides).
3. Test in headset: `PANEL_HOST=0.0.0.0 stack panel`, then from the 4080 box
   open `http://<mac-ip>:8787/vr/index.html` in Chrome with SteamVR running.

## Scripts (in `~/media-stack/scratch/`)

- `make_pig_3d.py` — Hunyuan3D image→3D. Flags: `--texture`, `--decimate N`,
  `--octree N`, `--no-unwrap`. 4 images = multi-view.
- `trellis_3d.py` — TRELLIS 2 three-stage pipeline; `--vcol` for vertex colours.
- `blender_repair.py` — GLB repair pass (the thing that made the asset usable).
- `render_asset.py` — fixed-camera render for A/B comparison.
- `pig_views.py`, `pig_hero.py`, `bench.py` — reference generation and timing.

## Hard-won constraints (do not rediscover)

- ComfyUI only rescans model dirs **at startup** — restart after downloading.
- `UnwrapMesh` OOMs on dense meshes; **decimate before unwrap**.
- `ApplyTextureToMesh` and `BakeTextureFromVoxel` both **require existing UVs**.
- Hunyuan/`SaveGLB` omits `NORMAL` → flat faceted shading. Clear custom split
  normals in Blender, then `shade_smooth`. Do **not** add a `Smooth by Angle`
  modifier (it re-splits normals at 30°).
- Never symlink Blender — use the `~/media-stack/bin/blender` wrapper.
- Full detail: `README.md` and the `local-media-stack` skill.
