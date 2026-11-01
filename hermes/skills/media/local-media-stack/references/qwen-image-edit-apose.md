# Getting an A-pose (or any pose change) from an existing image

Text-to-image and img2img both fail at this, for different reasons. Use an
instruction editor.

| approach | result |
|---|---|
| **Flux text-to-image**, pose described in detail | ignores it. Three attempts, both "relaxed A-pose" and a rigid "technical reference A-pose, arms 45 degrees out, palms facing thighs, no hand in pockets" — arms stayed at her sides / hand in pocket every time |
| **Flux img2img** at denoise 0.62 | cannot rotate or re-pose. Four view prompts (left/right/back) all returned *frontal* images, because it refines existing structure instead of moving limbs |
| **Qwen-Image-Edit 2509** | **works.** Real A-pose: arms ~45° out with clear space to the torso, hands open, full body |

Why: text-to-image can only draw what the prompt describes, and a pose is a
structural instruction it routinely loses. An instruction editor reads the actual person
and edits them, keeping face/hair/clothing.

## Exact graph (from ComfyUI's `image_qwen_image_edit_2509` template)

```
UNETLoader  qwen_image_edit_2509_fp8_e4m3fn.safetensors
CLIPLoader  qwen_2.5_vl_7b_fp8_scaled.safetensors   type=qwen_image
VAELoader   qwen_image_vae.safetensors

LoadImage -> FluxKontextImageScale          # scale reference to ~1 MP
TextEncodeQwenImageEditPlus(clip, prompt, vae, image1=<scaled ref>)   -> positive
TextEncodeQwenImageEditPlus(clip, "",      vae, image1=<scaled ref>)  -> negative

ModelSamplingAuraFlow(model, shift=3.0)
CFGNorm(model, strength=1.0, pre_cfg=False)
VAEEncode(scaled ref, vae)                  # latent comes from the REFERENCE
KSampler(steps, cfg, euler, simple, denoise=1.0)
VAEDecode -> SaveImage
```

**The reference is passed as conditioning (`image1` + `vae`), not as an img2img
latent.** That is the structural reason it can move limbs where img2img cannot. The
latent still comes from the reference, but denoise stays at 1.0.

## Settings

| mode | steps | cfg |
|---|---|---|
| Qwen Team reference | 50 | 4.0 |
| **Comfy default (used)** | **20** | **2.5** |
| with Lightning 4-step LoRA | 4 | 1.0 |

Lightning LoRA: `Qwen-Image-Edit-2509-Lightning-4steps-V1.0-bf16.safetensors`
(810 MB, `lightx2v/Qwen-Image-Lightning`, path `Qwen-Image-Edit-2509/`). Insert with
`LoraLoaderModelOnly` between the UNET and `ModelSamplingAuraFlow`.

## Models and cost

`Comfy-Org/Qwen-Image-Edit` → `split_files/diffusion_models/qwen_image_edit_2509_fp8_e4m3fn.safetensors` (19.0 GB)
`Comfy-Org/Qwen-Image` → `split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors` (8.7 GB)
`Comfy-Org/Qwen-Image` → `split_files/vae/qwen_image_vae.safetensors` (242 MB)
Also useful: `split_files/loras/Qwen-Edit-2509-Multiple-angles.safetensors` (225 MB) for turnarounds.

All three files are required — the diffusion model alone will not load.

Measured on M3 Max 64 GB: **20 steps ≈ 17 min** cold at ~1 MP (~49 s/step). With the
Lightning LoRA, 4 steps → ~4 min, which is what makes iteration affordable.

## Prompt that worked

> Re-pose this person into a clean technical A-pose: both arms held straight and
> outward away from the body at roughly forty five degrees, clear empty space visible
> between each arm and the torso, hands open and empty at the sides, legs straight and
> shoulder width apart, both feet flat and fully visible. Keep the same face, hair, body
> and clothing exactly. Full body from head to feet, plain flat neutral grey background,
> even studio lighting.

## Verify the result by asking about the arms specifically

Whole-image judgement says "looks fine". Ask whether there is **clear space between
the upper arm and the torso, and between the forearm and the hips** — that is what
makes it an A-pose rather than a relaxed stand, and it is what the 3D reconstruction
needs for limb separation.

## Download speed note

`hf_hub_download` sustained ~2–3 MB/s here; `HF_HUB_ENABLE_HF_TRANSFER=1` with
`hf_transfer` installed gave **13 MB/s** — worth doing before any 19 GB pull.
