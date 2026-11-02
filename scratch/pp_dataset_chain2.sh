#!/usr/bin/env bash
# After the outfit batch: extreme cameras, then facial expressions.
# Expressions run against the FACE master into their own output dir (native subject size is
# bigger there, so the mouth and eyes have pixels to work with).
set -u
cd /Users/dcruse/media-stack || exit 1
PY=ComfyUI/.venv/bin/python
BODY=output/image/pepper_body_MASTER.png
FACE=output/image/pepper_face_MASTER.png

echo "[chain2] waiting for the outfits batch"
while pgrep -f "pp_angles.py --master $BODY --fast --set outfits" >/dev/null 2>&1; do
  sleep 20
done

echo "[chain2] extremes"
$PY scratch/pp_angles.py --master "$BODY" --fast --set extremes 2>&1 | tee -a logs/pp_angles_batch.log

echo "[chain2] expressions"
$PY scratch/pp_angles.py --master "$FACE" --fast --set expressions \
  --outdir output/image/pepper_expr --size 1024x1024 2>&1 | tee -a logs/pp_expr.log

echo "[chain2] complete"
