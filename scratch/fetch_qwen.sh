#!/bin/bash
# Fetch Qwen-Image-Edit 2509 into ComfyUI's model folders.
#
# Four files are required: the diffusion model alone will not load without the
# matching Qwen 2.5-VL text encoder and the Qwen image VAE. Smallest first so the
# wiring can be tested before the 19 GB download finishes.
set -u
M="$HOME/media-stack/ComfyUI/models"
HF="https://huggingface.co"

get() {  # repo  remote-path  dest-dir
  local repo="$1" path="$2" dir="$3"
  local name; name="$(basename "$path")"
  mkdir -p "$dir"
  if [ -s "$dir/$name" ]; then
    echo "[skip] $name"
    return 0
  fi
  echo "[get ] $name"
  curl -L --fail --retry 5 --retry-delay 5 -C - \
       -o "$dir/$name.part" "$HF/$repo/resolve/main/$path" \
    && mv "$dir/$name.part" "$dir/$name" \
    && echo "[done] $name $(du -h "$dir/$name" | cut -f1)" \
    || echo "[FAIL] $name"
}

get "Comfy-Org/Qwen-Image"      "split_files/vae/qwen_image_vae.safetensors"                        "$M/vae"
get "Comfy-Org/Qwen-Image-Edit" "split_files/loras/Qwen-Edit-2509-Multiple-angles.safetensors"      "$M/loras"
get "Comfy-Org/Qwen-Image"      "split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors"   "$M/text_encoders"
get "Comfy-Org/Qwen-Image-Edit" "split_files/diffusion_models/qwen_image_edit_2509_fp8_e4m3fn.safetensors" "$M/diffusion_models"

echo "ALL DONE"
