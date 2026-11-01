# Photo → 3D asset: the proven gold-standard recipe

This is the exact path that produced the approved asset. Reproduce it in this order;
every step exists because skipping it caused a defect that had to be diagnosed later.

**Gold standard reference:** `~/media-stack/gold-standard/hog_trellis2_GOLD.glb`

| property | value |
|---|---|
| triangles | 699,804 |
| vertices | 412,904 |
| native size | 0.333 × 0.567 × 0.999 m (unscaled) |
| textures | 3 (base colour + metallic/roughness + normal) |
| attributes | NORMAL, POSITION, TANGENT, TEXCOORD_0 |
| texture luminance | mean 22.7, stddev 19.9 |
| sha256 (first 12) | 773c5fd37e8c |
| runtime | 16 min 16 s on an M3 Max, 64 GB |

It ships **with its fifth leg** — that is the generator's output, not an edit target.
It is the benchmark: a new asset should match or beat its texture stddev, attribute
set and surface continuity before you touch it downstream.

Full SHA256 is in `~/media-stack/gold-standard/SHA256SUMS`. Never let an experiment
overwrite this file; work on copies.

## Step 1 — reference image (this sets the ceiling)

Flux dev fp8, 1024², 20 steps, cfg 1.0, `euler`/`simple`. Generate 3–4 seeds, choose by
eye. Measured ≈ 160–216 s each.

### What the pose must be (single-image models)

A reconstruction infers depth from shading and silhouette, and cannot recover what it
cannot see. That makes one factor dominate everything else:

- **A-pose, limbs clear of the torso** — arms 30–45° off the body. Arms flush against
the chest fuse into the mesh because the far side of each limb is invisible.
- **Full body, nothing cropped** — head to feet with margin. Truncated limbs are where
  reconstructions go malformed, and it cannot invent pixels that were cropped away. A
  mid-shot cropped at the thighs reconstructed as a **kneeling figure with mitten
  hands**: the model guessed the missing lower body rather than omitting it, and the
  guess was wrong. Nothing downstream repairs that.
- **Slight 3/4 (15–30°) or dead-on front.** Pure profile is the worst case: one
  silhouette, no depth cue across the body's width. 3/4 gives a side plane *and*
facial volume.
- **Long lens, near-orthographic, camera at chest height.** A low or wide angle bakes
  perspective distortion straight into the geometry.
- **Flat even light, matte surfaces.** Reconstruction reads shading as surface, so a
  hard shadow under the chin becomes a crease in the mesh; specular highlights on skin
  or denim become noise.
- **Plain flat background, no props.** BiRefNet masks a clean edge better.

Prompt shape that worked for an animal subject (swap the species/breed):

> photorealistic <breed> standing broadside in profile facing left, <coat and mane>,
> <distinguishing anatomy>, the feet end in <trait by analogy>, the whole animal from
> snout tip to tail is inside the frame with clear margin, isolated on a clean bright
> white seamless background, no ground shadow, no floor, soft even studio light,
> extremely detailed <surface> texture, sharp focus

### Prompt block that produces a usable A-pose

Copy-paste, replace `SUBJECT HERE` with the character description:

```
full body studio photograph of SUBJECT HERE, standing in a relaxed A-pose with
arms held thirty to forty five degrees away from the torso and clearly separated
from the body, legs straight and slightly apart, both feet flat on the floor and
fully visible, facing the camera at a slight three-quarter angle, the entire figure
from head to feet inside the frame with even margin on all sides, plain flat neutral
grey seamless studio background, no props, no furniture, soft even diffused studio
lighting with no hard shadows, matte fabric, eighty five millimeter lens, camera at
chest height, photorealistic, sharp focus, high detail
```

Every constraint is phrased as what you want, never as a negative: at cfg 1.0 Flux is
guidance-distilled and ignores negative prompts entirely, so "no shadows" does nothing
while "soft even diffused lighting with no hard shadows" at least names the target.

For a multi-view consumer, same seed and same subject block, changing only the clause:

```
front → full body front view, facing the camera directly, A-pose
left  → full body left profile view, facing screen-right, A-pose
back  → full body rear view seen from directly behind, back of the head visible, A-pose
right → full body right profile view, facing screen-left, A-pose
```

### Re-posing an existing photo: pick the right kind of model

Flux dev **cannot edit at all** — it is text-to-image only. "Use Flux to fix the pose"
is not an option; the Flux editor is a different model.

| tool | size | good at | weak at |
|---|---|---|---|
| FLUX.1 Kontext dev | 11.1 GB fp8 | identity retention, text/object edits, inpaint | large structural change — fights a re-pose |
| Qwen-Image-Edit 2509 | ~20 GB fp8 (raw repo ~39 GB) | instruction following, character-preserving edits, multi-image refs | heavier and slower |
| + Qwen Multiple-Angles LoRA | +0.27 GB | camera-angle change — the turnaround tool | needs the Qwen base |
| ControlNet OpenPose (SDXL) | 2.33 GB | pose, precisely; SDXL base is already installed | SDXL quality ceiling |

**Pose belongs to pose conditioning, not to an instruction editor.** Editors try to
preserve the structure they are given, and re-posing changes occlusion and demands new
anatomy, which is exactly what they are built not to do. For a real photo that must
land in an A-pose, drive OpenPose ControlNet with a stick figure and keep identity via
img2img at 0.35–0.50 denoise.

img2img denoise guidance: **0.35–0.50** preserves face and outfit, above ~0.6 it starts
inventing, and 1.0 is simply text-to-image again. It never rotates the subject at any
value.

#### Qwen-Image-Edit 2509 wiring (four files, three of them required)

A diffusion model alone will not load — the Qwen image VAE and the Qwen 2.5-VL text
encoder are separate downloads:

| file | folder | size |
|---|---|---|
| `qwen_image_edit_2509_fp8_e4m3fn.safetensors` | `models/diffusion_models/` | 19.0 GB |
| `qwen_2.5_vl_7b_fp8_scaled.safetensors` | `models/text_encoders/` | 8.7 GB |
| `qwen_image_vae.safetensors` | `models/vae/` | 0.24 GB |
| `Qwen-Edit-2509-Multiple-angles.safetensors` | `models/loras/` | 0.23 GB |

The first and fourth come from `Comfy-Org/Qwen-Image-Edit`, the middle two from
`Comfy-Org/Qwen-Image`. **Restart ComfyUI afterwards or none of them appear in a combo.**

Graph: `UNETLoader` → optional `LoraLoaderModelOnly` → `KSampler`; `CLIPLoader` with
`type='qwen_image'` → `TextEncodeQwenImageEdit`, whose `vae` and `image` sockets are
**optional but must be connected** for image-conditioned editing; `VAEEncode` on the
source image supplies the latent. Prefer ComfyUI's shipped
`image_qwen_image_edit_2509.json` — but note it wraps the graph in a subgraph node, so
drive it through the UI (`app.loadGraphData` + `app.queuePrompt`) the way the 3D
templates are driven, not through `/prompt`. `template_qwen_multiangle.app.json` is the
turnaround variant.

### Verify the reference with two checks, in this order

1. **Whole-frame check**: full body in frame, plain background, no extra limbs or props.
2. **Zoomed trait check** (`vision_analyze` with a `region` box over the feet/face): the
   defining detail, asked about in isolation. Whole-frame judgement of a small detail is
   wrong in both directions — 6 of 6 candidates read "fused hooves" at full scale and
   "cloven" under a crop. **The zoom is the truth.**

Known, accepted deviation on that asset: the breed trait never came out. Six seeds,
negative and analogy phrasing, all cloven. Ship with the discrepancy stated and route
the fix to an inpaint or a geometric edit. Do not burn more seeds.

### img2img cannot re-pose a subject — generate the pose, do not refine it

Deriving a turnaround from one photo with img2img does not work. img2img refines the
structure already present, so a denoise of 0.6 on a frontal photo returns another
frontal photo; even 0.8 returned a front view. A measured attempt produced 4 of 4
"left/right/back" views all facing the camera.

Consequences:

- To get an A-pose, **generate it from text**. Do not try to rotate an existing photo.
- To re-pose a *specific* person or object you need explicit pose conditioning
  (OpenPose ControlNet) or a posed 3D proxy — not a higher denoise.
- A turnaround only has value where a node actually consumes multiple views. TRELLIS.2
  takes **one** image (`Trellis2Conditioning`: `clip_vision_model` + `image`), so four
  generated views buy nothing there.

## Step 2 — background removal is optional, not required

The template already runs `LoadBackgroundRemovalModel` → `RemoveBackground` internally,
so pre-cutting is redundant when you feed `LoadImage` directly. It is worth doing only
when the source background is busy enough that a clean pre-pass masks better:

```bash
<comfyui-venv-python> scratch/cutout_ref.py <hero.png> <cutout.png>   # ≈12 s
```

Use **ComfyUI's venv** for any PIL/image script — the mlx-audio venv has no PIL and
fails at import.

## Step 3 — feed the ORIGINAL; do not pre-crop or pre-pad to square

`ImageCropToMask` crops to the **subject's mask bounding box** (`pad_factor 1.1`) and
resizes to 1024². It is not a centre-crop, so:

- **aspect ratio is irrelevant** — a 2:3 portrait will not lose head or feet;
- pre-padding to a square gets re-cropped away and costs a double resample
  (1664×2496 → 800×1008 → 1229² → 1024² softens the reference);
- the crop follows the subject, so the only thing that matters is that the *source*
  does not cut the subject off at the frame edge.

## Step 4 — TRELLIS.2 through the real UI

The 66-node template cannot run through `/prompt` (`Save3DAdvanced` needs a
UI-injected `viewport_state`; no output node accepts MESH). Do it over CDP in this order:

1. Open `http://127.0.0.1:8188`.
2. Fetch `/templates/3d_pixal3d_trellis2_image_to_model.json` (served at that path,
   **not** under `/api/`).
3. `app.loadGraphData(wf)` — fire unawaited and poll a flag; 66 nodes exceed the CDP
   eval timeout.
4. Set `PrimitiveBoolean` → `true` (selects TRELLIS.2 over Pixal3D).
5. Point `LoadImage` at the staged reference (copy it into `ComfyUI/input/` first).
6. Set the `PrimitiveInt` bake resolution — see the memory note below before using 4096.
7. **Mute the dead Pixal3D/MoGe nodes**: ids `55, 56, 242, 298, 319`. Validation covers
   the whole prompt, not the selected branch, so uninstalled weights fail the job.
   Compare ids as strings or the loop matches nothing and never mutes.
8. `app.queuePrompt(0, 1)`.
9. Poll `/queue` until idle, then confirm a file appeared in `ComfyUI/output/3d/`.

**"status_str=success" is not success.** A prompt can report success in 0.02 s having
run nothing, when only preview nodes validated. The only proof is the GLB on disk.

### Bake resolution vs memory ceiling

The template's 4096 colour bake is sized for an animal on a 64 GB machine (peaks ~48 GB,
~5 s/step at the heavy stage). The step counter only advances when a step completes, so
a log that has not moved for two minutes on a slow stage is progressing, not stalled:
confirm with GPU utilisation before declaring a hang.

**Cost tracks subject size in frame and `RemeshMesh` resolution, not the bake** — do not
lower the bake to rescue a slow run. Two measured points on the same box:

| subject | remesh | bake | texture-stage cost |
|---|---|---|---|
| full-body humanoid | 1024 | 4096 | **12 s/step**, 25 min total, ~41 GB — fine |
| head-only bust (fills frame) | 1024 | 2048 | **400–440 s/step**, 2h35m — pathological |
| same head-only bust | **384** | 2048 | **3.4 s/step** |

A small subject at a high remesh is the failure case; the same bake resolution is fine
for a full body. Lower `RemeshMesh` first (a head at 384 is still denser than the body's
own head), and leave the bake alone.

Do not restart a long run on the first sign of slowness; check GPU busy % and the
elapsed/frame counter first.

## Step 5 — verify before anything else

```bash
<venv-python> scratch/qc_glb.py output/3d/ComfyUI_00001.glb --max-tris 900000
~/media-stack/bin/blender -b --python scratch/count_legs.py -- <glb>
~/media-stack/bin/blender -b --python scratch/render_asset.py -- <glb> out.png 900
```

- `qc_glb.py` passes only with NORMAL + TEXCOORD_0 + embedded PBR images + texture
  variation. It follows `baseColorTexture`, so a flat normal map will not fail a good
  asset.
- `count_legs.py` counts connected columns in the ankle slab. **It printed 5** on this
  asset — the generator added a limb. Count before you measure anything anatomical; a
  four-quadrant split averages the extra limb into a real one and every derived number
  is wrong (rear-left read 0.467, the mean of limbs at 0.395 and 0.546).
- Render and look, then zoom for the traits you care about.

If the limb count is right and the render is clean, **stop** — this is the gold standard
state. Everything past here is elective.

## Elective post-processing (not part of the gold standard)

Only when a downstream use demands it:

- **Remove an extra limb** — `scratch/remove_extra_leg.py`. It cuts the column nearest
  mid-body and caps **only that socket**; filling every boundary loop wrecks a surface
  that has ~1,585 islands and >100k boundary edges.
- **Scale to real units** — `scratch/scale_static.py --scale-to 2.0`. TRELLIS returns
  ~1 m regardless of the subject; the VR room treats 1 unit as 1 metre.
- **Rig it** — see `references/joint-picker.md`. Expect real work; animation is a
  separate project from the asset.

Keep the original untouched and copy forward. The gold standard is the reference point
for judging every later experiment.

## Step 6 — head detail (only when a face must survive)

A full-body recon cannot paint a face: it gets ~5% of the atlas and ~120 px in an
832-wide reference, so eyes bake as **black voids**. Raising the atlas does not help
(4096 → 8192 measured 892 → 889 laplacian). Reconstruct the head as its own subject:

1. **Crop the head from the highest-resolution photo you have**, not from the A-pose.
   A 1664×2496 source gave a 480 px-wide face against 120 px in the generated A-pose.
   Include hairline and neck — a chin-only crop reconstructs an open shell.
2. **BiRefNet cutout to plain white first.** A blurred background gives a noisy mask,
   which fragments the volume and makes the texture stage crawl.
3. **TRELLIS with `RemeshMesh` 384**, decimate ~250k, unwrap 2048, colour 4096.
4. **Merge by enclosure, not by cutting.** Cutting both meshes at the neck leaves the
   body's open rim visible as a hard ring even when the scales match. Instead scale the
   detail head to the body's measured head width (start **1.03**, not 1.10) and centre
   it so the original head becomes hidden interior geometry — no cut, no seam.
5. **Check the margin at two framings.** A 10% margin looks right in a head close-up and
   reads as an oversized head in a full-body render. Judge head *size* on the whole
   figure, face *detail* on the crop.

Measured on this box: head recon 2h35m at remesh 1024 versus minutes at 384 (see the
memory-ceiling table above); merged asset 1,449,291 tris, 2 materials, QC PASS.

What this does **not** fix: hair colour drifts lighter than the source, skin stays waxy
at this atlas size, and hands/feet stay simplified — their source is ~100 px, so a crop
recon would only upscale blur. Say so rather than iterating further.

## Choosing the model: TRELLIS.2 vs Hunyuan3D 2.0 / 2.1

| | TRELLIS.2 | Hunyuan3D 2.1 | Hunyuan3D 2.0 |
|---|---|---|---|
| inputs | 1 image | 1 image | 1 image **or** 4 views |
| texture | 3D-aware, 3 PBR maps | painted projection only | painted projection only |
| files | 4 separate (UNet + 2 VAE + DINO) | 1 all-in-one checkpoint | 3 split DiTs, all-in-one in practice |

**Hunyuan3D 2.0 is not a four-photo model.** It ships as several variants and only the
multi-view ones want four images:

- `hunyuan3d-dit-v2_fp16.safetensors` — **single image**
- `hunyuan3d-dit-v2-mv_fp16.safetensors` — four views
- `hunyuan3d-dit-v2-mv-turbo_fp16.safetensors` — four views, faster

All three live under `split_files/` in `Comfy-Org/Hunyuan-3D-2.0` (~4.6 GB each).
Despite the split-files layout and the absence of a VAE or vision file in the repo,
**the single-image DiT loads all-in-one**: drop it in `models/checkpoints/` and
`ImageOnlyCheckpointLoader` returns MODEL + CLIP_VISION + VAE from it, exactly like
2.1. ComfyUI's `3d_hunyuan3d_image_to_model.json` template does precisely this (it is
a subgraph — drive it through the UI, not as an API prompt).

Measured head to head on one A-pose reference, M3 Max 64 GB — what each engine
actually leaves on disk:

| engine | time | tris | textures | normals | UVs | QC |
|---|---|---|---|---|---|---|
| Hunyuan 2.0 (`dit-v2_fp16`) | **148 s** | — | none | ✗ | ✗ | fail |
| Hunyuan 2.1 (`hunyuan_3d_v2.1`) | 281 s | 128,146 | 1 projected | ✗ | ✓ | fail |
| **TRELLIS.2** | 448 s | 699,800 | **3 PBR** | ✓ (+TANGENT) | ✓ | **PASS** |

Hunyuan 2.0 returns `POSITION` and nothing else — a blockout, not an asset. 2.1 needs
`--decimate 200000` before unwrap if you want texture at all (4,163 charts in 18.5 s);
`--no-unwrap` and a texture request fails outright with `mesh has no UVs`.

In ComfyUI the multi-view node enforces nothing: `Hunyuan3Dv2ConditioningMultiView` has
**zero required inputs** and `front`/`left`/`back`/`right` are all optional sockets.
Four views only improve the mesh when they are a genuinely consistent turnaround;
independently generated views reconstruct **worse** than a single good image.

## Measured results on this machine

| stage | time |
|---|---|
| Flux hero, per seed | 160–216 s |
| BiRefNet cutout | 10–13 s |
| TRELLIS.2 full template, animal (700k tris, 3 PBR maps) | 16 min 16 s |
| TRELLIS.2 at 4096 bake, humanoid | ~20× slower per step; use 2048 |
| Blender scale + re-export | ~20 s |
| Blender render check | 30–60 s |
