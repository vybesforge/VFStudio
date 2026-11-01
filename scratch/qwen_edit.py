"""Qwen-Image-Edit 2509 — image-conditioned edit, all local.

Unlike Flux text-to-image this keeps the person in the source image: the edit
node takes both the CLIP and the image, so identity/hair/skin survive the change.
That is the whole point — the earlier A-pose was invented by a text prompt and
came back as a different woman.

  python qwen_edit.py --image src.png --prompt "..." --out out.png
"""

import argparse
import json
import shutil
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

COMFY = Path.home() / "media-stack" / "ComfyUI"
INPUT = COMFY / "input"
OUTPUT = COMFY / "output"
BASE = "http://127.0.0.1:8188"

UNET = "qwen_image_edit_2509_fp8_e4m3fn.safetensors"
CLIP = "qwen_2.5_vl_7b_fp8_scaled.safetensors"
VAE = "qwen_image_vae.safetensors"


def api(method, path, payload=None, timeout=120):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        f"{BASE}{path}", data=data, method=method,
        headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        print(f"\nHTTP {exc.code} from {path}:\n{body[:3000]}\n", file=sys.stderr, flush=True)
        raise


def build(image_name, prompt, negative="", seed=5, steps=20, cfg=2.5,
          megapixels=1.0, shift=3.0, loras=()):
    wf = {
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": UNET, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": CLIP, "type": "qwen_image", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "4": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "5": {"class_type": "ImageScaleToTotalPixels",
              "inputs": {"image": ["4", 0], "upscale_method": "lanczos",
                         "megapixels": megapixels, "resolution_steps": 1}},
        "6": {"class_type": "TextEncodeQwenImageEdit",
              "inputs": {"clip": ["2", 0], "prompt": prompt, "vae": ["3", 0],
                         "image": ["5", 0]}},
        "7": {"class_type": "TextEncodeQwenImageEdit",
              "inputs": {"clip": ["2", 0], "prompt": negative, "vae": ["3", 0],
                         "image": ["5", 0]}},
        "8": {"class_type": "VAEEncode", "inputs": {"pixels": ["5", 0], "vae": ["3", 0]}},
        "9": {"class_type": "ModelSamplingAuraFlow",
              "inputs": {"model": ["1", 0], "shift": shift}},
        "10": {"class_type": "KSampler",
               "inputs": {"model": ["9", 0], "positive": ["6", 0], "negative": ["7", 0],
                          "latent_image": ["8", 0], "seed": seed, "steps": steps,
                          "cfg": cfg, "sampler_name": "euler", "scheduler": "simple",
                          "denoise": 1.0}},
        "11": {"class_type": "VAEDecode", "inputs": {"samples": ["10", 0], "vae": ["3", 0]}},
        "12": {"class_type": "SaveImage",
               "inputs": {"images": ["11", 0], "filename_prefix": "qwen_edit"}},
    }

    # chain LoRAs between the UNET and the sampling-shift node
    src = ["1", 0]
    for i, (name, strength) in enumerate(loras):
        nid = f"l{i + 1}"
        wf[nid] = {"class_type": "LoraLoaderModelOnly",
                   "inputs": {"model": src, "lora_name": name,
                              "strength_model": strength}}
        src = [nid, 0]
    wf["9"]["inputs"]["model"] = src
    return wf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--negative", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("--steps", type=int, default=20)
    ap.add_argument("--cfg", type=float, default=2.5)
    ap.add_argument("--megapixels", type=float, default=1.0)
    ap.add_argument("--lora", action="append", default=[],
                    help="lora_name[:strength], repeatable")
    a = ap.parse_args()

    src = Path(a.image)
    if not src.is_file():
        sys.exit(f"missing image: {src}")
    INPUT.mkdir(parents=True, exist_ok=True)
    name = f"qwen_{src.stem}.png"
    shutil.copy(src, INPUT / name)

    loras = []
    for spec in a.lora:
        nm, _, st = spec.partition(":")
        loras.append((nm, float(st) if st else 1.0))
    wf = build(name, a.prompt, a.negative, a.seed, a.steps, a.cfg, a.megapixels,
               loras=loras)
    t0 = time.time()
    sub = api("POST", "/prompt", {"prompt": wf, "client_id": uuid.uuid4().hex})
    pid = sub.get("prompt_id")
    print("submitted", pid, flush=True)
    if not pid:
        sys.exit(f"submit failed: {sub}")

    deadline = time.time() + 1800
    entry = None
    while time.time() < deadline:
        time.sleep(2)
        try:
            hist = api("GET", f"/history/{pid}")
        except Exception:
            continue
        if pid in hist:
            entry = hist[pid]
            break
    if entry is None:
        sys.exit("timed out")

    status = entry.get("status") or {}
    if status.get("status_str") == "error":
        print(json.dumps(status, indent=2)[:2500])
        sys.exit("workflow errored")

    imgs = [i["filename"] for o in (entry.get("outputs") or {}).values()
            for i in o.get("images", [])]
    if not imgs:
        print(json.dumps(entry.get("outputs"), indent=2)[:1500])
        sys.exit("no image produced")

    dst = Path(a.out)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(OUTPUT / imgs[0], dst)
    print(f"done in {time.time()-t0:.1f}s -> {dst}")


if __name__ == "__main__":
    main()
