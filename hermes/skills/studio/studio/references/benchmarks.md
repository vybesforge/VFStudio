# Measured timings on this Mac (M3 Max, 64 GB, 40-core GPU)

All numbers: wall time of `gen …` including model load, idle machine unless noted.
Update this table when you measure; do not quote numbers you did not measure.

| Pipeline | Settings | Time | Notes |
|---|---|---|---|
| Z-Image-Turbo t2i | 1024², 8 steps | 53 s | measured WHILE a 10 GB download was writing — expect ~25-35 s idle |
| Flux dev fp8 t2i | 1024², 20 steps | ~226 s | from local-media-stack skill (earlier session) |
| TRELLIS.2 image→3D | template defaults, 700k tris | 9m32s | UI-driven, see local-media-stack |
| TRELLIS.2 HQ | 1.2M tris, 4096 bakes | 25m17s | |
| Kokoro TTS | 2 sentences | 0.1 s warm / ~45 s cold | mlx-audio |
| Qwen3-TTS clone | 1 sentence | 2.0 s warm / 6.4 s cold | +4.5 GB server RSS |
| Whisper large-v3-turbo | 5 s clip | 0.5 s warm / 2.9 s cold | |
| OrcaSlicer CLI | 15 mm cable clip, Bambu P1S | <5 s | |
| Godot Windows export | VR room | ~20 s | |
| gltf-transform optimize | 1.2M→100k tris, 4096→2048 tex | ~5 s | |

Pending first measurement (models downloaded 2026-11-01): FLUX.2 klein 4B, Z-Image ControlNet,
Wan 2.2 5B video, Stable Audio Open 1.0, Stable Audio 3 medium, ACE-Step 1.5, SeedVR2, ESRGAN.
