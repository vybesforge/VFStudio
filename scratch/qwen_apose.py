"""Re-pose an image into an A-pose using Qwen-Image-Edit 2509.

Graph mirrors ComfyUI's official `image_qwen_image_edit_2509` template minus the
Lightning 4-step LoRA (not installed here), so the standard sampler settings apply:

    Qwen Team  : steps 50, cfg 4.0
    Comfy default: steps 20, cfg 2.5
    4-step LoRA : steps 4,  cfg 1.0

Texture-critical details taken from that template and kept:
  - ModelSamplingAuraFlow shift 3
  - CFGNorm strength 1.0, pre_cfg False
  - FluxKontextImageScale on the reference (scales to ~1 megapixel)
  - the reference is passed to TextEncodeQwenImageEditPlus as image1 + vae, NOT as an
    img2img latent — this is an instruction edit, not a denoise-the-source pass

Usage:
  python qwen_apose.py --image IN.png --out OUT.png [--steps 20] [--cfg 2.5]
"""
import argparse
import json
import time
import urllib.request
from pathlib import Path

from PIL import Image

HOST = "http://127.0.0.1:8188"
COMFY = Path("/Users/dcruse/media-stack/ComfyUI")

UNET = "qwen_image_edit_2509_fp8_e4m3fn.safetensors"
CLIP = "qwen_2.5_vl_7b_fp8_scaled.safetensors"
VAE = "qwen_image_vae.safetensors"

APOSE_PROMPT = (
    "Re-pose this person into a clean technical A-pose: both arms held straight and "
    "outward away from the body at roughly forty five degrees, clear empty space "
    "visible between each arm and the torso, hands open and empty at the sides, legs "
    "straight and shoulder width apart, both feet flat and fully visible. Keep the "
    "same face, hair, body and clothing exactly. Full body from head to feet, plain "
    "flat neutral grey background, even studio lighting."
)


def api(path, payload=None, timeout=1800):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"{HOST}{path}", data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    return json.loads(raw) if raw else {}


def upsample_size(size, long_side):
    """Target size with `long_side` on the longer edge, kept multiple of 8."""
    w, h = size
    if w >= h:
        scale = long_side / w
    else:
        scale = long_side / h
    tw, th = int(round(w * scale / 8) * 8), int(round(h * scale / 8) * 8)
    return tw, th


def build(image_name, prompt, steps, cfg, seed, lora=None, lora_strength=1.0,
          long_side=None):
    wf = {
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": UNET, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": CLIP, "type": "qwen_image", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "4": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        # Scale the reference to ~1MP, as the official template does.
        "5": {"class_type": "FluxKontextImageScale", "inputs": {"image": ["4", 0]}},
        "6": {"class_type": "TextEncodeQwenImageEditPlus",
              "inputs": {"clip": ["2", 0], "prompt": prompt, "vae": ["3", 0],
                         "image1": ["5", 0]}},
        "7": {"class_type": "TextEncodeQwenImageEditPlus",
              "inputs": {"clip": ["2", 0], "prompt": "", "vae": ["3", 0],
                         "image1": ["5", 0]}},
        "8": {"class_type": "ModelSamplingAuraFlow",
              "inputs": {"model": ["1", 0], "shift": 3.0}},
        "9": {"class_type": "CFGNorm",
              "inputs": {"model": ["8", 0], "strength": 1.0, "pre_cfg": False}},
        "10": {"class_type": "VAEEncode",
               "inputs": {"pixels": ["5", 0], "vae": ["3", 0]}},
        "11": {"class_type": "KSampler",
               "inputs": {"model": ["9", 0], "positive": ["6", 0], "negative": ["7", 0],
                          "latent_image": ["10", 0], "seed": seed, "steps": steps,
                          "cfg": cfg, "sampler_name": "euler", "scheduler": "simple",
                          "denoise": 1.0}},
        "12": {"class_type": "VAEDecode",
               "inputs": {"samples": ["11", 0], "vae": ["3", 0]}},
        "13": {"class_type": "SaveImage",
               "inputs": {"images": ["12", 0], "filename_prefix": "qwen_apose"}},
    }
    # Optional 2x-class output: FluxKontextImageScale clamps the reference to ~1MP,
    # so generating above 1MP needs an explicit scale after it. More pixels here is
    # the only way to raise baked texture detail — the atlas stops helping.
    if long_side:
        w, h = upsample_size(Image.open(COMFY / "input" / image_name).size, long_side)
        wf["15"] = {"class_type": "ImageScale",
                    "inputs": {"image": ["5", 0], "upscale_method": "lanczos",
                               "width": w, "height": h, "crop": "disabled"}}
        for nid in ("6", "7"):
            wf[nid]["inputs"]["image1"] = ["15", 0]
        wf["10"]["inputs"]["pixels"] = ["15", 0]
        print(f"[qwen] reference scaled to {w}x{h}")
    # Lightning 4-step LoRA sits between the UNET and the sampling patch, exactly as
    # the official template places it.
    if lora:
        wf["14"] = {"class_type": "LoraLoaderModelOnly",
                    "inputs": {"model": ["1", 0], "lora_name": lora,
                               "strength_model": lora_strength}}
        wf["8"]["inputs"]["model"] = ["14", 0]
    return wf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default="/Users/dcruse/media-stack/scratch/hero_apose2.png")
    ap.add_argument("--out", default="/Users/dcruse/media-stack/scratch/apose_qwen.png")
    ap.add_argument("--steps", type=int, default=20)
    ap.add_argument("--cfg", type=float, default=2.5)
    ap.add_argument("--seed", type=int, default=5150)
    ap.add_argument("--prompt", default=APOSE_PROMPT)
    ap.add_argument("--lora", default=None,
                    help="LoRA filename, e.g. the Lightning 4-step")
    ap.add_argument("--lora-strength", type=float, default=1.0)
    ap.add_argument("--long-side", type=int, default=None,
                    help="upscale the reference to this long edge before sampling")
    a = ap.parse_args()

    src = Path(a.image)
    staged = COMFY / "input" / "qwen_apose_src.png"
    Image.open(src).convert("RGB").save(staged)
    print(f"[qwen] staged {src} -> {staged}  steps={a.steps} cfg={a.cfg} "
          f"lora={a.lora or 'none'} long_side={a.long_side}")

    t0 = time.time()
    wf = build("qwen_apose_src.png", a.prompt, a.steps, a.cfg, a.seed,
               lora=a.lora, lora_strength=a.lora_strength, long_side=a.long_side)
    r = api("/prompt", {"prompt": wf})
    pid = r.get("prompt_id")
    if not pid:
        print("[qwen] REJECTED:", json.dumps(r)[:900])
        return
    while True:
        time.sleep(4)
        h = api(f"/history/{pid}")
        if pid in h:
            break
    st = h[pid].get("status", {})
    if st.get("status_str") == "error":
        for m in st.get("messages", []):
            if m and m[0] == "execution_error":
                print("[qwen] ERROR:", json.dumps(m[1])[:700])
    imgs = [i["filename"] for o in h[pid].get("outputs", {}).values()
            for i in o.get("images", [])]
    if not imgs:
        print("[qwen] no image")
        return
    Image.open(COMFY / "output" / imgs[0]).save(a.out)
    print(f"[qwen] {time.time()-t0:.0f}s -> {a.out}")


if __name__ == "__main__":
    main()
