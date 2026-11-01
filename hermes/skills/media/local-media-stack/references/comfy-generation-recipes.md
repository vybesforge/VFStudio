# ComfyUI generation recipes (API-format) — what `gen` builds and why

All graphs below are lifted from the official templates shipped in
`ComfyUI/.venv/lib/python3.12/site-packages/comfyui_workflow_templates_json/templates/`
and implemented in `~/media-stack/tools/comfy/gen`. Status column: **verified** = ran
here and produced the file; **from-template** = parameters transcribed from the
template, not yet executed — treat the first run as a test and check the output file,
not the status string.

## Reading a template without the UI

- Model files + download URLs sit in `node.properties.models[]` (`name`, `directory`,
  `url`). Grep the whole JSON for `.safetensors` too — subgraph templates put URLs in
  a MarkdownNote instead.
- Newer templates are **subgraphs**: the top level has 3–8 nodes and the real graph is
  in `definitions.subgraphs[].nodes/links`. An input link from node id `-10` means
  "subgraph input socket"; follow the top-level node's `widgets_values` for its value.
- `widgets_values` order = the node's widget inputs in `/object_info` order, with two
  traps: seed widgets carry an extra `fixed|randomize` entry, and
  `COMFY_DYNAMICCOMBO_V3` inputs inline their chosen option's sub-inputs right after
  the key. Dotted keys (`resize_type.multiplier`) are how a sub-input is addressed in
  an API prompt.
- Check every combo value against `/object_info` before submitting; combos such as
  `CLIPLoader.type`, `TextEncodeAceStepAudio1.5.keyscale` (`"C major"` …) and
  `UnwrapMesh.segmenter` reject the whole prompt on one bad string.
- Prefer plain output nodes (`SaveImage`, `SaveAudio` = flac) over the `*Advanced`
  savers whose `format` is a dynamic combo.

## Per-model parameters

| pipeline | files (models/…) | loader + sampler settings | status |
|---|---|---|---|
| **Z-Image-Turbo** t2i | `diffusion_models/z_image_turbo_bf16`, `text_encoders/qwen_3_4b`, `vae/ae` | `UNETLoader` + `CLIPLoader(type=lumina2)`; `ModelSamplingAuraFlow(shift=3)`; `EmptySD3LatentImage`; KSampler 8 steps, cfg 1.0, `res_multistep`/`simple`; negative = `ConditioningZeroOut(positive)` | verified (1024², 53 s incl. load) |
| **Z-Image ControlNet Union** | + `controlnet/Z-Image-Turbo-Fun-Controlnet-Union` | `ModelPatchLoader` → `QwenImageDiffsynthControlnet(model, model_patch, vae, image, strength)` wraps the UNET, then the same AuraFlow+KSampler chain; latent size from `GetImageSize` of the control map; template preprocessor is `Canny(0.1, 0.32)` on an image scaled to 1024 max | from-template |
| **FLUX.2 klein 4B** (distilled) | `diffusion_models/flux-2-klein-4b`, `text_encoders/qwen_3_4b`, `vae/flux2-vae` | `CLIPLoader(type=flux2)`; `EmptyFlux2LatentImage`; `SamplerCustomAdvanced` with `RandomNoise`, `KSamplerSelect(euler)`, `Flux2Scheduler(steps=4, w, h)`, `CFGGuider(cfg=1.0)`; the `-base-4b` variant uses 20 steps, cfg 5 | from-template |
| **Flux dev fp8** | `checkpoints/flux1-dev-fp8` | `CheckpointLoaderSimple`; 20 steps, cfg 1.0, euler/simple; negative ignored | verified |
| **Wan 2.2 TI2V 5B** | `diffusion_models/wan2.2_ti2v_5B_fp16`, `text_encoders/umt5_xxl_fp8_e4m3fn_scaled`, `vae/wan2.2_vae` | `CLIPLoader(type=wan)`; `ModelSamplingSD3(shift=8)`; `Wan22ImageToVideoLatent(1280×704, length 121, optional start_image)`; KSampler 20 steps, cfg 5, `uni_pc`/`simple`; `CreateVideo(fps=24)` → `SaveVideo(format=auto, codec=auto)`. Template ships a Chinese quality negative prompt — keep it | from-template |
| **Stable Audio Open 1.0** (SFX) | `checkpoints/stable-audio-open-1.0`, `text_encoders/t5-base` | `CheckpointLoaderSimple` (model+vae) **plus a separate** `CLIPLoader(t5-base, type=stable_audio)` — the checkpoint is not all-in-one; `EmptyLatentAudio(seconds)`; KSampler 50 steps, cfg ~5, `dpmpp_3m_sde`/`exponential`; `VAEDecodeAudio` → `SaveAudio` | from-template |
| **Stable Audio 3 medium** | `checkpoints/stable_audio_3_medium`, `text_encoders/t5gemma_b_b_ul2` | same shape; KSampler 8 steps, cfg 1.0, `lcm`/`simple`; up to ~150 s per clip. Template's `qwen3.5_2b` encoder is only a prompt-rewriter branch — optional | from-template |
| **ACE-Step 1.5 turbo AIO** (music) | `checkpoints/ace_step_1.5_turbo_aio` | `CheckpointLoaderSimple` → `ModelSamplingAuraFlow(shift=3)`; `TextEncodeAceStepAudio1.5(clip, tags, lyrics, seed, bpm, duration, timesignature∈{2,3,4,6}, language, keyscale, generate_audio_codes=True, cfg_scale=2, temperature=0.85, top_p=0.9)`; `EmptyAceStep1.5LatentAudio(seconds)`; KSampler 8 steps, cfg 1, euler/simple; lyrics `[inst]` for instrumental | from-template |
| **RealESRGAN / 4x-UltraSharp** | `upscale_models/*.pth` | `UpscaleModelLoader` → `ImageUpscaleWithModel`; rescale with `ImageScaleBy` for non-4× factors | from-template |
| **SeedVR2 3B int8** (diffusion upscale) | `diffusion_models/seedvr2_3b_int8_convrot`, `vae/seedvr2_ema_vae_fp16` | `ImageScaleBy(×N)` → `SeedVR2Preprocess` → `VAEEncodeTiled(512/128)` → `SeedVR2Conditioning(model, latent)` gives pos+neg → KSampler 1 step, cfg 1, euler → `VAEDecodeTiled` → `SeedVR2PostProcessing(color_correction=lab)` | from-template |

## Model selection notes (2026)

- Fast local image on a Mac: Z-Image-Turbo (6B, Apache-2.0) and FLUX.2 klein 4B both
  fit easily in 64 GB and run in well under a minute; Flux dev stays for text rendering.
- Video: Wan 2.2 TI2V 5B is the Mac-sized pick (14B pairs need ~30 GB of fp8 weights
  and are slow on MPS). Expect minutes per 5-second clip; run with `gen video` and the
  7200 s default timeout.
- SFX vs music: Stable Audio (Open 1.0 / 3 medium) for sound effects and ambiences,
  ACE-Step 1.5 for full songs with lyrics, mlx-audio MiniMax-Music for quick instrumentals.
- Stability's `stabilityai/*` HF repos are gated (401); use the `Comfy-Org/*_repackaged`
  mirrors and `ComfyUI-Wiki/t5-base` for the encoder.
- Hermes `image_generate` (`image_gen.provider: comfyui`) exposes only the image models
  from this table (`z-image-turbo`, `flux2-klein-4b`, `flux1-dev-fp8`); everything else
  goes through `gen`.
