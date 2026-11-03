#!/usr/bin/env bash
# Finish the Pepper pipeline unattended:
#   1. extreme-camera shots + facial expressions (dataset variety Dylan asked for)
#   2. rebuild the LoRA dataset from both manifests
#   3. train the `pepper` LoRA (Z-Image, 512 px, rank 16)
# Each step is resumable; `lora train` already calls the panel's unload-all first.
set -u
cd /Users/dcruse/media-stack || exit 1
PY=ComfyUI/.venv/bin/python
BODY=output/image/pepper_body_MASTER.png
FACE=output/image/pepper_face_MASTER.png

echo "[final] extremes"
$PY scratch/pp_angles.py --master "$BODY" --fast --set extremes 2>&1 | tee -a logs/pp_angles_batch.log

echo "[final] expressions"
$PY scratch/pp_angles.py --master "$FACE" --fast --set expressions \
  --outdir output/image/pepper_expr --size 1024x1024 2>&1 | tee -a logs/pp_expr.log

echo "[final] building dataset"
$PY scratch/build_pepper_dataset.py 2>&1 | tee -a logs/pp_dataset.log

echo "[final] training lora"
lora train --dataset train/datasets/pepper --name pepper --model zimage \
  --steps 700 --rank 16 --res 512 --trigger pepper --save-every 175 2>&1 | tee -a logs/pp_lora.log

echo "[final] complete"
