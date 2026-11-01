"""Generate a turnaround (front/left/right/back) from one photograph.

Reality check baked into the design: a single frontal photo contains no information
about the back or the far side, so those views are *invented*, not recovered. img2img
with a shared, detailed subject description is the least-drifting option available
here — every view starts from the same pixels instead of from noise. Even so, expect
identity drift; label the outputs accordingly.

Usage:
  python flux_views.py --image SRC.png --outdir DIR [--only back] [--seed 4242]
"""
import argparse
import json
import time
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

HOST = "http://127.0.0.1:8188"
COMFY = Path("/Users/dcruse/media-stack/ComfyUI")
CKPT = "flux1-dev-fp8.safetensors"

# The subject description is repeated in every view prompt. Without it each view
# reframes the person independently and the turnaround stops describing one subject.
SUBJECT = (
    "young woman, athletic toned physique, light brown hair in a high messy bun with "
    "loose strands framing her face, freckles, small earrings, dark olive green tight "
    "short-sleeved crop top, medium-wash blue low-rise denim jeans with visible "
    "stitching"
)

VIEWS = {
    "front": ("full-body front view, standing straight, facing the camera",
              0.30),
    "left":  ("full-body view from her left side, perfect side profile, facing left",
              0.62),
    "right": ("full-body view from her right side, perfect side profile, facing right",
              0.62),
    "back":  ("full-body rear view, seen from directly behind, back of the head and "
              "jeans visible", 0.80),
}


def api(path, payload=None, timeout=1800):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"{HOST}{path}", data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    return json.loads(raw) if raw else {}


def workflow(image_name, prompt, denoise, seed):
    return {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": CKPT}},
        "2": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "3": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt, "clip": ["1", 1]}},
        "4": {"class_type": "CLIPTextEncode",
              "inputs": {"text": "", "clip": ["1", 1]}},
        "5": {"class_type": "VAEEncode",
              "inputs": {"pixels": ["2", 0], "vae": ["1", 2]}},
        "6": {"class_type": "KSampler",
              "inputs": {"model": ["1", 0], "positive": ["3", 0],
                         "negative": ["4", 0], "latent_image": ["5", 0],
                         "seed": seed, "steps": 26, "cfg": 1.0,
                         "sampler_name": "euler", "scheduler": "simple",
                         "denoise": denoise}},
        "7": {"class_type": "VAEDecode",
              "inputs": {"samples": ["6", 0], "vae": ["1", 2]}},
        "8": {"class_type": "SaveImage",
              "inputs": {"images": ["7", 0], "filename_prefix": "turnaround"}},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--outdir", default="/Users/dcruse/media-stack/scratch/turnaround")
    ap.add_argument("--only", nargs="*", default=list(VIEWS))
    ap.add_argument("--seed", type=int, default=4242)
    args = ap.parse_args()

    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)

    # Resize to a Flux-friendly size (multiple of 8, ~1 megapixel, portrait kept).
    src = Image.open(args.image).convert("RGB")
    w, h = src.size
    scale = (832 * 1248 / (w * h)) ** 0.5
    nw, nh = max(8, int(w * scale) // 8 * 8), max(8, int(h * scale) // 8 * 8)
    resized = src.resize((nw, nh), Image.LANCZOS)
    dest = COMFY / "input" / "turnaround_src.png"
    resized.save(dest)
    print(f"[views] source {w}x{h} -> {nw}x{nh} -> {dest}")

    for view in args.only:
        clause, denoise = VIEWS[view]
        prompt = (f"photorealistic studio photograph, {SUBJECT}, {clause}, "
                  "whole body inside the frame with clear margin, isolated on a clean "
                  "bright white seamless background, no ground shadow, no props, "
                  "soft even studio light, sharp focus, high detail")
        t0 = time.time()
        r = api("/prompt", {"prompt": workflow("turnaround_src.png", prompt,
                                               denoise, args.seed)})
        pid = r.get("prompt_id")
        if not pid:
            print(f"[views] {view}: REJECTED {json.dumps(r)[:600]}")
            continue
        while True:
            time.sleep(4)
            hist = api(f"/history/{pid}")
            if pid in hist:
                break
        outs = hist[pid].get("outputs", {})
        saved = [i["filename"] for o in outs.values() for i in o.get("images", [])]
        if not saved:
            print(f"[views] {view}: no image produced")
            continue
        src_img = COMFY / "output" / saved[0]
        final = out / f"view_{view}.png"
        Image.open(src_img).save(final)
        print(f"[views] {view}: {time.time()-t0:.0f}s -> {final}")


if __name__ == "__main__":
    main()
