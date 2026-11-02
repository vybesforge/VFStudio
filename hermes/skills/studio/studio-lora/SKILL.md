---
name: studio-lora
description: "Use when training a LoRA for a recurring subject or style."
version: 1.0.0
author: Jimmy
license: MIT
platforms: [macos]
metadata:
  hermes:
    tags: [studio, lora, training, ai-toolkit, z-image, flux, mps, local-inference]
    category: studio
---

# studio-lora — train a LoRA locally (ai-toolkit on Apple Silicon)

> **Save deliverables under `~/media-stack/ComfyUI/models/loras/ (LoRAs) and train/datasets/<name>/ (datasets)`** — that is where the VF Studio panel (http://127.0.0.1:8787) looks; files elsewhere never show up or preview there. Any subfolder inside is fine.

A LoRA teaches Z-Image / FLUX.2 klein a recurring subject (a character, Dylan's BMW parts, a
product) or a style, so every generation stays consistent. Trainer: ostris **ai-toolkit** in
`~/media-stack/train/.venv` (torch 2.13, MPS), wrapped by the `lora` CLI. Output lands in
`~/media-stack/ComfyUI/models/loras/<name>.safetensors`, which `gen image --lora` reads.

## When to Use
- Same subject needed across many images/videos and prompts alone drift.
- A house style (render look, illustration style) to apply repeatedly.
- Not for one-offs — `gen edit` (Qwen-Image-Edit) handles single-image changes with no training.

## Prerequisites
```bash
lora status          # venv ok · trainer ok · torch 2.13.0 mps · zimage unet/extras/adapter ok · comfy queue: 0
```
Memory: Z-Image training at 512 px needs the whole machine. `lora train` calls the panel's
unload-all first (`--keep-models` skips that). Do not run `gen` jobs during training.

## Dataset rules (follow exactly)
- 8–20 images of ONE subject, 768–1024 px, varied angles/backgrounds, no other subjects.
  **20 is a floor for variety, not a cap**: 30–60 images are worth generating when the
  variety is real (different camera angles, poses, outfits, expressions) — redundant
  near-duplicates are what damage a small dataset, not the count.
- One `.txt` per image with a caption that contains the literal token `[trigger]`,
  e.g. `[trigger], three-quarter view, studio light, white background`. Caption the
  wardrobe and pose explicitly so the trigger binds identity, not a costume.
- Folder: `~/media-stack/train/datasets/<name>/`. Generate a synthetic set with klein:
  `~/media-stack/train/gen_dataset.sh` shows the pattern (10 × `gen image … --model klein --seed N`).
- **A real person needs a different recipe than a synthetic subject**: build the set
  with Qwen-Image-Edit from one hero photo (identity anchor + A-pose body master +
  neck-up face master, then orbit/extreme-camera/pose/outfit/expression batches).
  Procedure, prompt rules and cost: `references/character-dataset.md`.

## Recipes
```bash
# train (zimage, 512 px, rank 16). Trigger word replaces [trigger] in captions.
lora train --dataset ~/media-stack/train/datasets/vfrobot --name vfrobot --model zimage --steps 1000 --rank 16 --res 512 --trigger vfrobot --save-every 250
# → {"ok": true, "lora": ".../ComfyUI/models/loras/vfrobot.safetensors", "steps": 1000, "seconds": …, "sec_per_step": …, "size_mb": 81.2}
lora list                                    # LoRAs ComfyUI can see
stack restart comfy                          # once, after a NEW lora file appears
gen image "vfrobot toy robot on a workbench, soft light" --model zimage --lora vfrobot:0.9 --seed 1
```
Flags: `--resume` · `--lr 1e-4` default · `--model klein|flux` wired but **unverified**.

## Measured on this Mac (M3 Max 64 GB)
- Z-Image, 512 px, rank 16, batch 1, 10 images, **60 steps: 731 s = 12.2 s/step average**
  (6.5 s/step until unified memory filled, ~23 s/step once swap engaged). LoRA file 81 MB.
  Budget **1000 steps ≈ 3.5 h** — run overnight with `--save-every 250`.
- Loss 0.49 → 0.33 by step 30 on the synthetic robot set.
- 768 px or rank 32 will swap harder; stay at 512/16 on 64 GB.

## Verify
```bash
lora status | grep -q 'trainer:  ok' && lora list | grep -q vfrobot && echo LORA_OK
```

## Pitfalls (hit while building)
- **Batched caption caching OOMs on MPS**: ai-toolkit's `cache_text_embeddings` encodes 10 captions at once through Qwen3-4B; MPS SDPA tried to allocate 88 GB. `lora train` disables it by default (encodes per step); `--te-cache` re-enables it for CUDA boxes.
- `PYTORCH_ENABLE_MPS_FALLBACK=1` is set by the wrapper; without it some ops abort.
- The Z-Image text encoder is **symlinked** from ComfyUI (`train/models/Z-Image-Turbo/text_encoder/model.safetensors → ComfyUI/models/text_encoders/qwen_3_4b.safetensors`) — do not delete either.
- ostris `zimage_turbo_training_adapter` (de-distillation adapter) is required for Z-Image-Turbo; `--no-adapter` only for experiments.
- The first run (60 steps) proves the pipeline, not the look — far too few steps to learn a subject. The with/without comparison via `gen image --lora vfrobot` is still to be done after a 500+ step run.
