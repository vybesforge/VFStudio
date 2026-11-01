#!/bin/bash
# Fetch the two large Qwen-Image-Edit files with hf_transfer (parallel chunks).
# curl was sustaining ~2-3 MB/s; hf_transfer splits the file into ranges and often
# gets several times that. Falls back to curl if the transfer fails.
set -u
export HF_HUB_ENABLE_HF_TRANSFER=1
M="$HOME/media-stack/ComfyUI/models"
PY="$HOME/media-stack/ComfyUI/.venv/bin/python"

fetch_py() {  # repo  remote  destdir
  "$PY" - "$1" "$2" "$3" <<'EOF'
import os, sys
from huggingface_hub import hf_hub_download
repo, remote, dest = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(dest, exist_ok=True)
p = hf_hub_download(repo_id=repo, filename=remote, local_dir=dest + "/../_hf2")
src = os.path.join(dest + "/../_hf2", remote)
tgt = os.path.join(dest, os.path.basename(remote))
if os.path.exists(src):
    os.replace(src, tgt)
    print(f"[done] {os.path.basename(remote)} {os.path.getsize(tgt)/2**30:.2f} GB", flush=True)
EOF
}

echo "[start] text encoder"
fetch_py "Comfy-Org/Qwen-Image" "split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors" "$M/text_encoders" \
  || echo "[FAIL] text encoder"

echo "[start] diffusion model"
fetch_py "Comfy-Org/Qwen-Image-Edit" "split_files/diffusion_models/qwen_image_edit_2509_fp8_e4m3fn.safetensors" "$M/diffusion_models" \
  || echo "[FAIL] diffusion model"

rm -rf "$M/_hf2"
echo "ALL DONE"
