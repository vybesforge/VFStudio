#!/usr/bin/env bash
# Chain the rest of the Pepper dataset batches behind the angle orbit run.
# The orbit batch (--set angles) is already in flight; wait for it, then poses, then
# outfits. Each run is resumable (existing files are skipped), so a failure here can be
# restarted without redoing finished images.
set -u
cd /Users/dcruse/media-stack || exit 1
PY=ComfyUI/.venv/bin/python
MASTER=output/image/pepper_body_MASTER.png

echo "[chain] waiting for the angles batch to finish" 
while pgrep -f "pp_angles.py --master $MASTER --fast" >/dev/null 2>&1; do
  sleep 30
done
echo "[chain] angles batch done; starting poses"
$PY scratch/pp_angles.py --master "$MASTER" --fast --set poses 2>&1 | tee -a logs/pp_angles_batch.log
echo "[chain] poses done; starting outfits"
$PY scratch/pp_angles.py --master "$MASTER" --fast --set outfits 2>&1 | tee -a logs/pp_angles_batch.log
echo "[chain] all batches complete"
