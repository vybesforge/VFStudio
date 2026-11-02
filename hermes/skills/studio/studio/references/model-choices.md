# Model choices — what is installed, why, and what was rejected (audited 2026-11-02)

`bin/forge-recommend` turns the table below into a per-machine fetch list (`models/manifest.json`
`fit` blocks). Essentials / quality / optional, largest GPU only, 0.75 GB slack so a 4080's
16376 MiB still counts as 16 GB, Apple Silicon prefers the Qwen-Image-Edit GGUF and the MLX
repos. Read the table before changing a `fit` threshold.

Read this before suggesting "a newer model". Every row was checked against three gates:
**runs on MPS in 64 GB** (fp8 has no Metal kernel → upcasts to bf16, double the size; int8-convrot
runs but dequantises), **licence allows Dylan's commercial use**, **measured here**, not quoted.

| Task | Installed (default first) | Why | Rejected / deferred |
|---|---|---|---|
| Text→image | **Z-Image-Turbo** (Apache-2.0, 8 steps, 50 s/1024²) · FLUX.2 klein 4B (23 s) · Flux dev fp8 (best text, 226 s) | best quality/licence/speed balance on MPS | **FLUX.3 klein** 5.6B (newer, better) — gated repo + *FLUX Kommunity* licence is non-commercial unless a "Qualifying User"; revisit if Dylan accepts terms. **Qwen-Image 2.1 / 2512** — research-only licence, 20 GB fp8 → 39 GB on MPS |
| Image edit | **Qwen-Image-Edit 2509 Q4 GGUF** (13 GB, ComfyUI-GGUF) + Lightning 4-step LoRA; fp8 fallback | only open editor that keeps identity; GGUF avoids the 39 GB upcast | **Qwen-Image-Edit 2511** (newer) — no public Q4 GGUF yet; int8-convrot 20.5 GB would upcast. Swap in when a GGUF appears (manifest id pattern `qwen-image-edit-2511-gguf`) |
| ControlNet | Z-Image Fun ControlNet Union (`model_patches/`) | matches the default t2i | — |
| Upscale | ESRGAN / UltraSharp (8 s) · **SeedVR2 3B int8** (diffusion, 40 s for 2×) | 3B is the memory-sane one | SeedVR2 **7B** fp16 (16 GB) — marginal gain, slower; add only for hero stills |
| Video | **Wan 2.2 TI2V 5B** (Apache-2.0, 832×480×49f in 372 s) · **HunyuanVideo 1.5** 720p-i2v + 480p-t2v cfg-distilled fp16 (8.3B, SOTA open quality; `gen video --model hyv15 "prompt" [--image start.png]` — graph written from the official template, **not yet run on this Mac**: first run must record time + memory here) | 5B = fast path; HyV1.5 = quality path | **LTX-2.5** 22B — 44 GB bf16 on MPS, no. **Wan 2.2 14B** — 27 GB fp8 → 54 GB, no. Lip-sync (Wan S2V 14B) — same problem → run on the RTX 4080 / V100 box |
| SFX | **Stable Audio 3 Small-SFX** (`--model sa3sfx`, 6 s clip in 4.1 s) · Stable Audio Open 1.0 (`sao`, 12.4 s, CC) · SA3 medium (`sa3`, long clips) | Small-SFX is purpose-built for effects and 3× faster; A/B listened by Dylan pending | — |
| Music | **ACE-Step 1.5 turbo AIO** (30 s track in 72 s) · MiniMax-Music3 via mlx-audio | lyrics + structure tags, fast | ACE-Step 1.5 **XL** turbo (10 GB + 8.4 GB encoder) — heavier, not measured; YuE2 3B int8 |
| Stems | Demucs **htdemucs** (MPS, 5–8 s / 30 s) · htdemucs_ft | standard | — |
| TTS | **Kokoro-82M** (0.1 s) · **Qwen3-TTS 1.7B** clone (2 s warm) · Chatterbox-turbo fallback | mlx-audio native | VoiceStudio etc. are apps, not APIs |
| STT | **Parakeet-TDT 0.6B v3** (0.6 s / 8 s clip, 25 EU languages, top open WER) · Whisper-large-v3-turbo fallback (99 languages, 3.5 s) · Qwen3-ASR 1.7B 8-bit (CJK) | switched 2026-11-02; identical transcript, 6× faster | Nemotron 3.5 Transcribe — not in mlx-community yet |
| Writer LLM | **Qwen3.8-27B-Uncensored OptiQ 4-bit** (mlx-lm, ~6 words/s) | uncensored by choice, fits with image gen | bigger (70B+) will not coexist with ComfyUI in 64 GB |
| Vision | **Qwen3-VL-8B 4-bit** (mlx-vlm, 6 s/answer) | best small open VLM; camera via imagesnap | — |
| 3D | **TRELLIS.2** (MIT, via ComfyUI UI, 9.5 min) | gold-standard hog came from it | Hunyuan3D 2.1 (7.4 GB) — licence excludes EU/UK; weights removed from disk |
| LoRA training | ostris **ai-toolkit** (Z-Image, 12 s/step @512) | only trainer proven on MPS here | SimpleTuner / kohya untested |

## Platform facts that decide these choices (measured)
- fp8 safetensors on MPS: ComfyUI upcasts to bf16 → Qwen-Image-Edit 20 GB became 39 GB resident, 10 GB swap, 26–65 s/step. **Prefer GGUF Q4/Q5 or bf16 of a smaller model** over fp8 of a bigger one.
- int8-convrot files load (SeedVR2 3B int8 works) but dequantise — no speed win on Metal. `ComfyUI-MPS-INT8` / `ComfyUI-AppleSilicon-Optimized` node packs claim native int8/fp8 kernels: **untested here, next experiment**; could make 2511 / Qwen-Image 2512 viable.
- Unified memory is one pool: writer LLM (16 GB) + Z-Image (20 GB) + mlx-audio (6 GB) coexist; anything ≥ 20 GB wants the machine alone → panel *Unload all* first.

## How to re-audit (10 minutes)
1. `ls ~/media-stack/ComfyUI/.venv/lib/python3.12/site-packages/comfyui_workflow_templates_json/templates/ | sed 's/\.json//'` — the template pack is Comfy's list of currently supported models; new names = new candidates.
2. For a candidate: HEAD the HF URL for size (`x-linked-size` header), check `gated` and the licence file, compute MPS-resident size (fp8 × 2).
3. Add to `models/manifest.json`, `fetch-models <id>`, `stack restart comfy`, build the `gen` graph from the template's node list (`/object_info/<Node>` for exact inputs), run once, record the time in `benchmarks.md` and update the table above. Never quote a number you did not measure.
