---
name: studio-vision
description: "Use when you must look at an image or the camera locally."
version: 1.0.0
author: Jimmy
license: Apache-2.0
platforms: [macos, linux]
metadata:
  hermes:
    tags: [studio, vision, vlm, camera, mlx-vlm, qwen3-vl, local-inference]
    category: studio
---

# studio-vision — local image understanding + camera

> **Save deliverables under `~/media-stack/output/camera/`** — that is where the VF Studio panel (http://127.0.0.1:8787) looks; files elsewhere never show up or preview there. Any subfolder inside is fine.

A Qwen3-VL-8B vision model runs in MLX on this Mac (`mlx_vlm.server`, port 8082). It
describes, answers questions about, compares and OCRs images, and `imagesnap` grabs frames
from the FaceTime camera. Nothing leaves the machine. Use it instead of a cloud vision call
whenever the image is private or the pipeline must stay on-device; `vision_analyze` (cloud)
remains fine for quick QC of generated art when Dylan has not asked for local-only.

## When to Use
- "What is in this picture / on the camera?", "read the text in this screenshot", "compare
  these two renders" — locally.
- QC of generated assets (`gen image`, renders) without sending pixels off-box.
- Capturing a reference photo of a real object (for photo → 3D, for a sprite, for a prompt).

## Prerequisites (exact paths)
```bash
see status                 # {"up": true, "model": "mlx-community/Qwen3-VL-8B-Instruct-4bit", "camera": true}
stack start vision         # if up:false — loads ~5 GB, ready in ~30 s; stack stop vision frees it
see devices                # lists cameras ("FaceTime HD Camera")
```
`see` = `~/media-stack/tools/vision/see` (symlinked on PATH). Server venv `~/media-stack/llm/.venv`.
Model weights: `~/.cache/huggingface/hub/models--mlx-community--Qwen3-VL-8B-Instruct-4bit`.
Camera shots land in `~/media-stack/output/camera/`. Panel: http://127.0.0.1:8787 → Vision tab
(Ask / Describe / OCR / Snap / Snap & ask, gallery of shots).

## Recipes
Every command prints one JSON line `{"ok": true, "text": "...", "seconds": 6.1}` (plain text on a TTY).

**Describe an image** (~6 s)
```bash
see describe ~/media-stack/output/image/zimage_00002_.png
```

**Ask a specific question** — the way to QC a trait (hooves, hands, text) instead of a vague "is it good?"
```bash
see ask ~/media-stack/output/image/zimage_00002_.png "Are the hooves cloven or solid? Count the legs."
```
Measured: correctly reported cloven hooves, erect ears, bristly coat on the hog reference.

**Compare two images** (first, second)
```bash
see compare a.png b.png "Which has sharper fur texture and fewer artifacts? Answer A or B and why."
```

**OCR**
```bash
see ocr screenshot.png
```

**Camera: capture, or capture + ask**
```bash
see snap                                   # -> output/camera/snap_YYYYMMDD_HHMMSS.jpg
see snap --ask "What object am I holding up? Estimate its size."
see snap --warmup 3 --out ~/media-stack/scratch/ref.jpg   # longer exposure settle, custom path
```
First use: macOS asks for camera permission for the terminal app — grant it, re-run.

**Use a camera shot as a generation reference**
```bash
see snap --out ~/media-stack/scratch/ref.jpg && gen control "same object as a bronze statue" --image ~/media-stack/scratch/ref.jpg
```

## Verify
```bash
see status | grep '"up": true' && see ask ~/media-stack/output/image/zimage_00002_.png "What animal?" | grep -i pig && echo VISION_OK
```

## Pitfalls (hit while building)
- **`huggingface_hub` XET transfer silently downloaded nothing** (metadata only, weights absent, no error). Download with `HF_HUB_DISABLE_XET=1 hf download <repo>` — 5.8 GB landed in ~60 s that way. `install.sh` does this.
- `mlx_vlm.server` defaults to host 0.0.0.0 — the panel starts it with `--host 127.0.0.1`; keep it loopback.
- Memory: VLM ~5 GB resident alongside ComfyUI; stop it (`stack stop vision`) before a Flux dev / Qwen-Edit run on a busy box.
- Answers are from an 8B model: good at description, counting and OCR; weaker at fine aesthetic judgment. Ask narrow, checkable questions.
