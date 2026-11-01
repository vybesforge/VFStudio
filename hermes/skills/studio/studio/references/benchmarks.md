# Measured timings on this Mac (M3 Max, 64 GB, 40-core GPU) — 2026-11-01

Wall time of `gen …` including model load/submit, via the CLI. "idle" = no download or other
job running. Update this table when you measure; never quote a number you did not measure.

| Pipeline | Settings | Time | Notes |
|---|---|---|---|
| Z-Image-Turbo t2i | 1024², 8 steps | **50 s** idle, warm (≈6 s/step); 53–60 s cold/during downloads | default for Hermes `image_generate`; strong prompt adherence |
| FLUX.2 klein 4B t2i | 1024², 4 steps | **23 s** incl. first load | fastest; excellent photoreal — use when speed matters |
| Flux dev fp8 t2i | 1024², 20 steps | ~226 s | earlier session; 27 GB resident |
| Z-Image + ControlNet Union (canny) | 1024, 8 steps | 93 s incl. load, during download | composition held from edges |
| RealESRGAN x4 / 4x-UltraSharp | 1024→4096 | 8 s | `--scale 2` rescales after the 4× pass |
| SeedVR2 3B int8 upscale | 1024→2048 | 40 s | laplacian var 69→114 (real added detail, not just resize) |
| Wan 2.2 TI2V 5B video | 832×480, 49 f, 20 steps | **372 s** (14 s/step) during download | 1280×704×121 f will be ~4× longer; budget 20–30 min |
| Stable Audio Open 1.0 sfx | 6 s, 50 steps | 10 s | 44.1 kHz |
| Stable Audio 3 medium | 20 s, 8 steps | 10 s | up to 150 s clips, 44.1 kHz stereo |
| ACE-Step 1.5 turbo music | 30 s, 8 steps | 72 s | 48 kHz stereo FLAC; `[inst]` for instrumental |
| TRELLIS.2 image→3D | template defaults, 700k tris | 9 m 32 s | UI-driven, see local-media-stack |
| TRELLIS.2 HQ | 1.2M tris, 4096 bakes | 25 m 17 s | |
| Kokoro TTS | 2 sentences | 0.1 s warm / ~45 s cold | mlx-audio |
| Qwen3-TTS clone | 1 sentence | 2.0 s warm / 6.4 s cold | +4.5 GB server RSS |
| Whisper large-v3-turbo | 5 s clip | 0.5 s warm / 2.9 s cold | |
| OrcaSlicer CLI | 15 mm cable clip, Bambu P1S | <5 s | |
| Godot Windows export | VR room | ~20 s | |
| gltf-transform optimize | 1.2M→100k tris, 4096→2048 tex | ~5 s | |
