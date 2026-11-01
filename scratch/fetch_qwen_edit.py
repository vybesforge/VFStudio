"""Download Qwen-Image-Edit 2509 into ComfyUI's model folders.

ComfyUI splits this model across three files plus a LoRA — the diffusion model alone
will not load without the matching Qwen 2.5-VL text encoder and the Qwen image VAE.

Chosen: 2509 fp8 (19.0 GB) rather than 2511, because Comfy-Org ships a matching
Multiple-angles LoRA for 2509 — that pair is what makes turnarounds work.
"""
import os
import sys
from pathlib import Path

from huggingface_hub import hf_hub_download

MODELS = Path("/Users/dcruse/media-stack/ComfyUI/models")

FILES = [
    ("Comfy-Org/Qwen-Image-Edit",
     "split_files/diffusion_models/qwen_image_edit_2509_fp8_e4m3fn.safetensors",
     MODELS / "diffusion_models"),
    ("Comfy-Org/Qwen-Image",
     "split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors",
     MODELS / "text_encoders"),
    ("Comfy-Org/Qwen-Image",
     "split_files/vae/qwen_image_vae.safetensors",
     MODELS / "vae"),
    ("Comfy-Org/Qwen-Image-Edit",
     "split_files/loras/Qwen-Edit-2509-Multiple-angles.safetensors",
     MODELS / "loras"),
]

for repo, remote, dest_dir in FILES:
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / Path(remote).name
    if target.exists() and target.stat().st_size > 1_000_000:
        print(f"[skip] {target.name} already present "
              f"({target.stat().st_size/1073741824:.2f} GB)", flush=True)
        continue
    print(f"[get ] {repo}/{remote}", flush=True)
    hf_hub_download(repo_id=repo, filename=remote,
                    local_dir=str(dest_dir.parent / "_hf_tmp"))
    # hf_hub_download mirrors the repo layout; move into place.
    src = dest_dir.parent / "_hf_tmp" / remote
    if src.exists():
        os.replace(src, target)
        print(f"[done] {target.name} {target.stat().st_size/1073741824:.2f} GB", flush=True)
    else:
        print(f"[warn] expected {src} — not found", flush=True)

print("ALL DONE")
