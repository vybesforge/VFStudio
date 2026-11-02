# Project state — read this first

## 2026-11-02 (desktop): Services tab → Endpoints ("point other programs here")

`control/panel.py` gained an `ENDPOINTS` list + `GET /api/endpoints`; the **Services** tab renders one
card per service with that service's **endpoint tiles inside it** — mlx-audio holds TTS
`/v1/audio/speech`, STT `/v1/audio/transcriptions` and voice clone; then ComfyUI `:8188`, writer LLM
`:8081/v1`, VLM `:8082/v1`, panel API `:8787`. Each tile has **Copy** and a **curl** panel
(method/path/schema + a working snippet); **Copy all → .env / JSON** and the host switch sit above the
grid and flip every link between `127.0.0.1` and the LAN IP (`192.168.1.44`). The service card's status
pill is the start/stop toggle. Cards re-render only when the host changes — status updates patch the pill
and port line in place, so an open log or curl panel is not collapsed by the 2.5 s poll.
Verified both toggle directions on the pill (ComfyUI came back responding in 6 s).
Verified live: TTS returned a 24 kHz wav, STT transcribed `output/voice/clone_*.wav`, `/object_info`
returned 1033 nodes; clipboards checked by stubbing `navigator.clipboard.writeText`. Caveat: the
LLM/VLM rows were checked against `tools/llm/scribe` + `tools/vision/see` request bodies, not by
starting those 16/5 GB models.

## 2026-11-02: BLUE HOUR (browser extraction shooter)

`game/bluehour` — Three.js/TS/Vite FPS, playable at `npm run dev` (:5199). Verified: movement/collision,
gunplay, AI nav, contracts, extraction, results/restart, 19 unit tests.
Second pass added: **dialogue** (Meridian radio VO + branching Voss/Kess conversations, 25 Kokoro lines
generated locally via `tools/gen_vo.sh` → `public/vo/*.mp3`), **Blender-authored infected bodies**
(`tools/zombie_build.py` → `public/models/zombie.glb`, 11 bone-space parts + face decals + emissive eyes),
and **post-processing** (bloom + blue-hour grade + vignette/grain, `src/render/post.ts`).
Skill `browser-3d-game` holds the harness workflow. FPS not measurable here (SwiftShader only).

Last updated: 2026-11-01 late (desktop session) — **studio build-out, round 2**

## 2026-11-01 (evening): round 2 — what changed since the table below
- **Published**: https://github.com/vybesforge/VFStudio (`main`, history rewritten so no GLBs/models/joints are tracked; `*.glb`, `gold-standard/`, `rig/joints_*.json`, `output/`, `train/*`, `stems/.venv` gitignored). Push via a one-shot credential helper with the fine-grained PAT in `~/Desktop/gitderp.rtf` (needs Contents: read+write). Local assets were restored from `known-good/` after the rewrite reset the tree (gold sha 773c5fd37e8c intact).
- **Writer LLM** `scribe` (:8081, Qwen3.8-27B-Uncensored 4-bit, thinking off) · **vision** `see` (:8082, Qwen3-VL-8B, camera via imagesnap / V4L2 on Linux). Panel Write + Vision tabs.
- **Panel**: VF branding + ko-fi link; Resources → *Unload all / Stop everything*; Edit card (Qwen-Image-Edit), Stems card (Demucs), **Upload…** buttons for every path field (image/voice/model → `output/<kind>/uploads/`), **Record from mic** for voice-clone references; `voice clone` auto-transcribes the reference with Whisper. `stack restart panel|llm|vision` now works. Legacy page removed.
- **VR room** rewritten: any GLB via `?src=`, per-asset joint picker (`&rig=1`, quadruped/biped templates, mirror, undo), controller rays + trigger pick/teleport, foveation, >300k-tri warning. `rig.html` redirects.
- **`gen edit`** (Qwen-Image-Edit 2509): works; prefers the Q4 GGUF (`unet/Qwen-Image-Edit-2509-Q4_K_M.gguf`, ComfyUI-GGUF node pack) because fp8 upcasts to 39 GB on MPS (measured 5–9 min/edit). GGUF path downloaded and node registered; **first GGUF-path timing not yet measured** — run `gen edit … --fast` alone and record it in `studio` skill.
- **Game + animation**: Godot 2D/3D templates (`game/`), `tools/anim/` (Rigify auto-rig, Grease Pencil, sprite sheets), Tahoma2D installed (OpenToonz is x86-only on macOS). Skills `studio-game`, `studio-animation`.
- **Stems**: `stems split|karaoke` (Demucs htdemucs on MPS, 5–8 s per 30 s). Skill `studio-stems`.
- **LoRA training**: ai-toolkit in `train/.venv`, `lora train|status|list`, `gen image --lora NAME[:s]`. First real run (Z-Image, 512 px, rank 16, 60 steps) was **in progress at hand-off**: 6.5 s/step early, ~23 s/step once swap engaged. Batched caption caching OOMs on MPS → disabled by default. Verify the produced `ComfyUI/models/loras/vfrobot.safetensors` with/without and update `studio-lora`.
- **Ubuntu port**: `INSTALL-UBUNTU.md` written from the code (speaches + llama-server replace MLX; CUDA ComfyUI). **Not executed anywhere yet.**
- **Deferred — lip-sync / talking head**: Wan 2.2 S2V 14B is ~30 GB fp8 → ~60 GB bf16 on MPS; not viable on this Mac alongside anything. Run it (or LatentSync) on the RTX 4080 / V100 box instead; template `video_wan2_2_14B_s2v` exists in ComfyUI.

Open items: first `gen video --model hyv15` run (graph untested) and GGUF edit timing; finish + verify first LoRA; headset test (Godot .exe, WebXR controller picking); run `install.sh` on a clean Mac; run `INSTALL-UBUNTU.md` once on the Precision box.

## 2026-11-01: one-stop studio (image · video · 3D · VR · print · sound · music · voice)

Entry point for any agent: **skill `studio`** (router) → `studio-video-edit`, `studio-voice`,
`studio-3d-print`, `studio-vr`, `local-media-stack` (deep 3D reference). Panel at
http://127.0.0.1:8787 is now the Studio page (tabs per modality, run forms, live ComfyUI
progress bar, output galleries with inline preview, Models inventory). Legacy page at `/legacy`.

| Area | Tool | Models | Verified |
|---|---|---|---|
| Image | `gen image` (Z-Image-Turbo default, FLUX.2 klein 4B, Flux dev) + Hermes `image_generate` | manifest | Z-Image 50 s warm idle (6 s/step); klein 23 s; see studio/references/benchmarks.md |
| Control | `gen control` (Z-Image Fun ControlNet Union, canny or raw map) | ✓ (`models/model_patches/`!) | 93 s, composition held |
| Upscale | `gen upscale` esrgan / ultrasharp / seedvr2 | ✓ all three | ESRGAN 8 s; SeedVR2 2× 40 s, laplacian 69→114 |
| Video | `gen video` (Wan 2.2 TI2V 5B) | ✓ | 832×480×49f, 20 steps: 372 s (14 s/step) |
| Video edit | `vid`, `vse_build.py` (Blender 5.2 VSE), `transcribe_srt.py` | — | all subcommands tested |
| SFX | `gen sfx` (Stable Audio Open 1.0 / Stable Audio 3 medium) | ✓ both | SAO 6 s in 10 s; SA3 20 s in 10 s |
| Music | `gen music` (ACE-Step 1.5 turbo AIO) | ✓ | 30 s track in 72 s |
| Voice | `voice say/clone/transcribe/enhance` (Kokoro, Qwen3-TTS clone, Whisper) | ✓ HF cache | clone 2 s warm; transcript matched |
| 3D | TRELLIS.2 via UI (unchanged gold path); Hunyuan checkpoints **removed from disk** | ✓ | — |
| Print | build123d examples, `meshcheck.py`, `slice --preset bambu|generic` (OrcaSlicer 2.4.2 CLI) | — | sliced 3 parts both presets |
| VR | Godot 4.7.2 OpenXR room `vr-godot/`, Windows .exe export, `optimize_glb.sh`, `vr/view.html` | — | headless load + exports OK; headset untested |

GUI apps added via Homebrew: Krita, Audacity 4, Inkscape, OpenSCAD (snapshot), MeshLab; plus
OrcaSlicer and Godot (direct). `sox` via brew. Tools venv `tools/.venv` (3.12): build123d,
trimesh, pymeshfix, moviepy, pedalboard, librosa.

Model manifest: `models/manifest.json` (~136 GB total). `fetch-models --list` shows state.
Hermes `image_gen.model` = `z-image-turbo`; plugin rewritten (explicit model table — audio
checkpoints in `models/checkpoints` are no longer mistaken for SDXL).

ComfyUI progress on the panel works because `gen` and the Hermes plugin submit with
`client_id: gen-cli` and the panel's websocket listens under that id (ComfyUI only sends
per-step progress to the submitting client). UI-submitted jobs show an indeterminate bar.

Open items: test the Godot Windows build on the 4080 box; run `install.sh` on a second Mac to
prove the repro (only tested idempotently on this one); the panel's Voice
clone form needs a reference wav path (use the gallery "as ref" button).

---


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

## Known-good snapshot (rollback point)

Dylan approved the current pig. Before any experimental pipeline work, snapshot:

```
~/media-stack/known-good/20261031-1130/
├── assets/pig_clean.glb        <- the vetted asset (sha256 in SHA256SUMS)
├── assets/pig_reference.png    <- the Flux reference that drove it
├── assets/render_clean.png, render_raw_hunyuan.png
├── scripts/                    <- make_pig_3d.py, blender_repair.py, render_asset.py
├── STATE.md, README.md
└── SHA256SUMS
```

Restore (verifies checksums first, refuses on mismatch):

```bash
restore-known-good              # newest snapshot
restore-known-good --list       # list snapshots
restore-known-good 20261031-1130
```

It restores the asset into `vr/`, points `vr/pig.glb` (the file the room loads)
at the vetted asset, and restores the scripts into `scratch/`.

Take a fresh snapshot before each experiment round:
`cp -R` the same set into `known-good/$(date +%Y%m%d-%H%M)/` and regenerate
`SHA256SUMS`.

## Defect found in the approved asset (2026-10-31, late)

`pig_clean.glb` renders well but carries a **flat pedestal fused to the feet**:
24% of its vertices sit in the bottom 5% of its height, and 25% in the top 5%
(flat slabs). The mesh is a single connected component, so the base is welded to
the hooves — it cannot be removed by "separate by loose parts".

Root cause: the reference image had a plain studio backdrop, and Hunyuan
reconstructed the *ground* as geometry.

**Fix is upstream, not downstream:** run `cutout_ref.py` (BiRefNet inside
ComfyUI) on the reference *before* meshing, so no ground plane is ever inferred.
Trimming the pedestal afterwards is a patch, not a repair.

Correction to an earlier claim: this is **not** a separate backdrop wall. When
blender_repair*separated by loose parts before welding* it reported 22,270
fragments (the raw GLB is split at every UV seam) and the sheet heuristic
mis-fired. Weld first, then the mesh is 1 component.

## QC gate (`scratch/qc_glb.py`)

Automated pass/fail before an asset reaches VR: NORMAL present, TEXCOORD_0,
embedded texture, texture luminance stddev (catches blank bakes), triangle
budget, real-world scale, and a planar-sheet detector. Run against the known
assets it correctly passed the good pig and failed the untextured TRELLIS
variants.

## Mulefoot hog (2026-10-31, delivered)

`vr/hog_animated.glb` — 245,999 tris, 1.97 × 1.10 × 0.55 m, NORMAL+UV+4096 albedo+AO,
trot animation (24f), QC PASS. Room loads it and reads `anim: Trot`.

Pipeline that produced it: Flux hero (1024², 4 seeds) → **cutout_ref.py (BiRefNet)**
→ `make_pig_3d.py --octree 512 --decimate 250000 --texres 4096` → `blender_repair.py`
(4096) → `qc_glb.py` → `animate_asset.py`.

**The cutout step is what fixed the pedestal.** The hog has correct long/narrow
proportions and no ground plane, unlike the previous pig.

### Paint upside-down bug — FIXED (crop to subject bbox)

Two causes, both fixed:
1. `blender_repair.py` flipped V with `1.0 - v`. Blender's V already runs
   bottom-to-top. Removed the flip.
2. The photo carries white margin (left 60, top 249, right 45, bottom 131 px on a
   1024² cutout). The planar projection normalises the mesh bbox against the whole
   image, so that margin landed on the hog's back → light back, dark belly. Fix:
   `crop_tight.py` crops to the subject bbox first (`hog_cutout_tight.png`, 927×652).

### Legs swinging sideways — FIXED (world axis → bone local)

Rotating leg bones on local X splayed them sideways; bone roll is undefined unless
set. Now the swing axis is built in world space (horizontal, perpendicular to
travel) and converted per bone: `pb.bone.matrix_local.to_3x3().inverted() @ axis`,
with `QUATERNION` rotation mode. Result: 35 fcurves, legs swing fore/aft along the
body. Verified in renders — frame 1 shows a proper mid-stride fore/aft pose.

### Texture plan — the model is already installed, no download needed

`Trellis2TextureStage` + `VaeDecodeTextureTrellis` with
`trellis_2_texture_vae_bf16.safetensors` is the real 3D-aware texture model and it is
already in this ComfyUI install. The earlier failure was self-inflicted: stripping the
template workflow dropped its `RescaleCFG` / `CFGOverride` nodes. Fix = run the
template as-shipped against the clean hog + reference image. Also present:
`Hunyuan3Dv2ConditioningMultiView` (multiview 3D), `BakeTextureFromVoxel`,
`MeshTextureToImage`, `ApplyTextureToMesh`. Cloud API texture nodes exist
(`Tencent3DTextureEditNode`, `MeshyTextureNode`, `TripoTextureNode`) — avoid, they
ship the asset off-device.

### TRELLIS.2 3D-aware texture — SHIPPED (this is the good one)

`vr/hog_trellis2_anim.glb` — 699,802 tris, 3 PBR textures (base colour + metal/rough
+ normal), 2.0 m, trot animation, QC PASS. In the room as `pig.glb`.

Run via `scratch/run_trellis2.py`, 16 min 16 s. Result: texture is continuous across
ALL surfaces — no white patches, no tiling. That is the thing projection could not do.

**Driving this template headlessly is impossible.** `Save3DAdvanced` requires a
`viewport_state` (`LOAD_3D`) socket that only the web UI injects, and no output node
accepts MESH (`MeshToFile3D` has output_node=False, so it never executes on its own).
So the pipeline is driven through the real UI via CDP:
load `/templates/3d_pixal3d_trellis2_image_to_model.json` with `app.loadGraphData`,
set `PrimitiveBoolean` → true, point `LoadImage` at the reference, mute the dead
Pixal3D/MoGe nodes (ids 55,56,242,298,319 — uninstalled models fail validation even
when the switch bypasses them), then `app.queuePrompt`.

**Weight bug (important):** bone-heat binding silently fails on a 700k mesh —
"Bone Heat Weighting: failed to find solution", groups exist but are empty, and the
exporter writes no skin, so the asset carries animation curves but never deforms.
`animate_asset.py` now verifies non-zero weights per bone and falls back to
`proximity_weights()` (numpy point-to-segment, two-bone blend, bucketed assignment).
Verify with `test_deform.py`, never by eyeballing a render.

**Body splitting with the legs — fixed.** Plain nearest-segment weighting let leg
bones claim the snout and back (a long leg segment is closer than the short spine
bone). Three gates were needed, and each one only surfaced after the previous fix:
1. legs may only claim vertices below the hip line (`hip_z = 0.52` of height) with a
   `band = 0.12` ramp;
2. damping applies to the SECOND-nearest bone as well as the nearest — damping only
   the nearest left up to 0.5 leg weight on the back (0.27 measured above 70%);
3. the gate itself must be RADIAL (`radius = 0.16 * L`, in metres), not normalised
   coordinate windows. Windows at `along 0.72 ± 0.22` still reached into the face,
   and belly/opposite-flank verts rode the legs — which is what read as a phantom
   fifth leg swinging out of the body.
4. **The rig needed a `head` bone.** `root` ended at 78% of body length, so the face
   had no nearby bone at all and bound entirely to the front legs.

Result: upper-body displacement spread 0.046 m → 0.016 m (all RIGID); rendered frames
4/7/13 show exactly four legs at every phase.
Audit with `audit_weights.py`. It reports leg weight per height band plus BOTH ends of
the body — both ends have legs, so a leg weight of 1.0 at one end is normal and must
not be read as a leak.

**qc_glb fix:** it judged `images[0]`. With a PBR set that is often the normal map
(legitimately flat), so it now follows `baseColorTexture` via the material binding.

### Mulefoot hooves — reference is the root cause

Both pipelines produce cloven hooves, and zooming always shows it while whole-image
checks wrongly claim "fused". The reference photo is cloven, so no reconstruction can
invent fused hooves. Fix is upstream: inpaint the reference (Flux Fill) or a
geometric fuse in Blender.

### Projection texturing limit — superseded

Projection texturing only covers surfaces the photo saw. The far flank, belly and
inner legs project onto the photo's white background, so the asset reads as "white
body with dark patches". Four attempts all failed differently:

| attempt | failure |
|---|---|
| BOX triplanar, scale 2.2 | tiled the photo → repeated pig silhouettes |
| BOX triplanar, scale 1/extent | still tiled |
| BOX + `extension=EXTEND` | still tiled; most samples hit background |
| planar UV projection | correct alignment on the side, but no coverage elsewhere |

**The fix is a 3D-aware paint model, not a parameter**: Hunyuan3D-2.1 paint via MLX
(the path the Avatar Forge doc lists, up to 4096). That is the next real step.

### Also settled
- Mulefoot fused hoof: 6/6 Flux candidates rendered **cloven** despite both
  "fused/no clef" and horse-hoof analogy phrasing. Accepted; needs inpaint
  (Flux Fill) or a geometric fuse in Blender.
- `qc_glb.py` slab check disabled by default — it contradicted a good render.
- Blender 5.x: `Action.fcurves` is gone (use layers/strips/channelbags).
- glTF import into Blender is **Z-up**; scripts must not assume Y-up after import.

## Face detail: what actually fixes it (measured 2026-11-01)

A full-body TRELLIS recon cannot paint a face. Measured, not assumed:

- The face gets **~5% of the 4096 atlas** (~500 px wide), and the reference crop
  gives it **~120 px** in an 832-wide A-pose. That is ~15 px per eye.
- Result: eyes bake as **black voids** — no iris, no sclera.

Ranked fixes, with what was measured:

| approach | verdict |
|---|---|
| raise body atlas 4096 -> 8192 | **no gain**: laplacian var 892 -> 889. Detail is source-limited, not atlas-limited |
| recon the head as its own subject | **works**: head fills frame, owns a whole atlas; eyes/brows/lips/hair all resolve |
| hand-crop recon | not worth it: hands are ~100 px in source, so it just upscales blur |

**Head-only recon recipe** that produced the good face:
1. Crop head+neck from the *highest-res* photo available (ppimage.png 1664x2496 ->
   1054x1045 crop; her face is 480 px there vs 120 px in the A-pose).
2. BiRefNet cutout to plain white first — a blurred background gives a noisy mask,
   which fragments the volume and makes the texture stage crawl.
3. TRELLIS with **remesh 384**, decimate 250k, unwrap 2048, colour 4096.
4. Merge onto the body by **enclosure, not cutting** — see below.

**Texture stage cost is driven by remesh resolution on small subjects.** At
remesh 1024 a head-only recon ran **400-440 s/step** (2h35m total); at remesh 384
the same job ran **3.4 s/step**. On the full body, remesh 1024 is fine (12 s/step).
Suspect this before assuming the machine is thrashing.

**Merge by enclosure, never by cutting.** Cutting both meshes at the neck leaves the
body's open rim visible as a hard ring, even when the scales match to 1%. Instead:
scale the detail head **1.10x**, centre it on the body's head, drop the crowns
together, and let the original head become hidden interior geometry. No cut, no
rim, no seam — verified in render.

## HQ profile for TRELLIS.2 (measured 2026-10-31)

Template defaults vs a high-quality profile, and what each change actually bought:

| knob | default | HQ | verdict |
|---|---|---|---|
| ImageCropToMask | 1024² | 1536² | helps, feeds more detail to the shape stage |
| Trellis2UpsampleStage | 1536 | 2048 | helps |
| structure steps | 12 | 20 | cleaner silhouette |
| upsample steps | 20 | 28 | " |
| texture steps | 12 | 20 | sharper albedo |
| RemeshMesh resolution | 768 | **1024** | **biggest geometric win** |
| DecimateMesh | 700k | **1.2M** | keeps that detail |
| UnwrapMesh | 2048 | 4096 | no texture smearing |
| BakeAmbientOcclusion | 1024 | 2048 | surface relief |
| BakeNormalMapFromMesh | 2048 | 4096 | " |
| BakeTextureFromVoxel | 2048 | 4096 | **already maxed — 8192 buys nothing at this poly count** |

Measured on the same A-pose input:

| build | tris | time | laplacian var (texture detail) |
|---|---|---|---|
| default | 699,890 | 9m32s | 663 |
| HQ | 1,199,384 | 25m17s | **892 (+35%)** |

The 4096 unwrap on 1.2M faces survived in ~41 GB RAM; the earlier OOM happened at
380k UV charts, so watch chart count rather than face count.

`scratch/texture_diff.py` compares base-colour sharpness between two GLBs — use it
instead of eyeballing renders, which judged the HQ texture as *flatter* when it was
measurably sharper.

**Ceiling that no setting fixes:** on a human from one image, hands come out as blobs,
feet blocky, hair a solid mass, skin smooth. Retopo or manual sculpt is the only fix.

## GOLD STANDARD (approved by user, 2026-10-31)

`~/media-stack/gold-standard/hog_trellis2_GOLD.glb` — sha256 `773c5fd37e8c…`,
699,804 tris, 412,904 verts, 0.333 × 0.567 × 0.999 m, 3 PBR textures,
NORMAL + POSITION + TANGENT + TEXCOORD_0, tex mean/std 22.7/19.9, **no animation**.

The user's words: "the hog_trellis2.glb is the gold standard … its perfect (without
the animation)". It ships with the fifth leg because that is the generator's raw
output. Copy it forward for any experiment; never overwrite it.

Reproduction recipe: skill `local-media-stack`, file
`references/photo-to-3d-gold-standard.md`.

### Animation: parked, and the leg axis is still wrong

The rig work (island-rigid skinning, joint picker) is sound and measured clean, but the
user reports the legs swing the wrong way. Do not resume animation without fixing that
first — and do not treat any rigged variant as a deliverable until it is.

## Jaw riding the legs (2026-10-31)

The snout/jaw hung low and forward, inside the front legs' capture cylinder, so those
islands bound to a leg. Two gates, both needed:
1. no leg may claim anything forward of the front legs (`head_along = front_leg_along
   + 0.03`);
2. islands forward of that line are locked to body bones outright (60 islands).

**Gate placement matters more than the gate.** The first attempt used the neck
(~0.84) as the boundary, but the front-left leg sits at along 0.869 — so the gate
locked the front leg itself out of leg binding (`FL_upper` collapsed to 273 verts).
The boundary must be forward of the FRONT LEGS, not the neck.

Measured: head displacement spread 0.170 m → 0.0069 m (HEAD STILL), edge stretch still
1.00×, every bone carries geometry.

**Test-metric trap:** the earlier head check selected "along > 0.86", which includes
the front-left leg at 0.869, so it reported HEAD MOVING WITH LEGS no matter what.
`test_deform.py` now excludes vertices with leg-bone weight > 0.1 from the head set.

**Rule: when a locality gate "doesn't work", check whether the gate line cuts through
the thing it is supposed to protect.**

## Two structural findings that solved the "rig" bugs (2026-10-31)

### 1. The mesh had FIVE legs

TRELLIS generated a five-legged hog. Every earlier measurement split the underside
into four quadrants, which silently averaged the extra limb into a real one (the
bogus rear-left along = 0.467 was the mean of limbs at 0.395 and 0.546). Rasterising
the low slab and counting connected columns exposed it:

    rear right 0.317/0.656 · rear left 0.395/0.321 · EXTRA 0.546/0.358
    front right 0.808/0.696 · front left 0.869/0.280

`remove_extra_leg.py` finds >4 columns, cuts the one nearest mid-body, and caps ONLY
the socket (filling every boundary loop wrecked the surface — this mesh has 1,585
islands and >100k boundary edges).

**Rule: never measure limbs with a fixed four-quadrant split.** Count connected
columns instead.

### 2. Skinning must be island-rigid on a soup mesh

The mesh is ~1,585 separate islands. Vertex-level weighting (nearest-bone, then
radius-gated, then Laplacian-smoothed) tore wherever one island spanned two bones —
that was the "smearing across the screen". Binding each island wholesale to its
dominant bone makes intra-island stretch impossible:

| approach | max edge stretch | edges >2x |
|---|---|---|
| nearest bone | 123.5× | 3,905 |
| + smoothing + far-bone cutoff | 32.0× | 5,212 |
| parametric cylinder capture | 29.3× | 4,979 |
| **island-rigid** | **1.00×** | **0** |

Trade-off: joints do not bend smoothly (rigid chunks). Soft bending needs a welded /
retopologised mesh, which is a separate job.

`test_deform.py` reports max edge stretch and counts edges >2× — that is the gate for
smearing. Ignore "upper-body displacement spread" on an island-rigid asset: it now
measures rigidity differences between islands, not tearing.

## Joint picker — hand-placed anatomy beats heuristics (2026-10-31)

Auto-rigging was the weak link and its failure was structural, not a tuning problem:
the hog's legs are **not symmetric** (measured rear-left along 0.467 vs rear-right
0.380, front 0.849/0.820), and bone-heat weighting dies on a 700k mesh. Measured
reality vs what the bbox rig assumed:

| | bbox rig assumed | measured |
|---|---|---|
| front legs | along 0.72 | 0.83 |
| rear legs | along 0.26 | 0.42 |
| leg radius | 0.16 gate | 0.03–0.08 |

So: **the user picks the joints; the machine does the rest.**

- `vr/rig.html` — Three.js picker at http://127.0.0.1:8787/vr/rig.html. Loads the
  room asset, 16 joints (neck, head, spine, hips + hip/knee/hoof per leg), click a
  joint then click the surface, auto-advances, save + build buttons. Points are
  recorded in the GLB's own glTF space (the model is deliberately NOT re-centred).
- `POST /api/rig/joints`, `POST /api/rig/build`, `GET /api/rig/build/status` in
  `control/panel.py`.
- `scratch/rig_from_joints.py` — builds the armature from the joints, converts
  glTF Y-up → Blender Z-up as `(x, -z, y)`, scales to 2.0 m, weights by distance to
  the picked bone segments with legs gated below their own hip joint and inside a
  radius derived from the picked chain length (`0.34 × chain`).
- `scratch/seed_joints.py` — writes a starter joints.json from measured geometry so
  the picker opens pre-populated instead of blank.

Result: upper-body displacement spread **0.0011–0.0057 m** (all RIGID), versus
0.0162 with the best automatic gate, and renders show four legs with no mouth
distortion.

**Lesson:** when a rig misbehaves, measure where the limbs actually are before
tuning weights. Every gate I added was compensating for bones placed in the wrong
place.

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
