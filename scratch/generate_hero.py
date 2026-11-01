"""Generate the A-pose hero image used as the shared input for all three engines.

Full body, A-pose, plain background — the pose spec that gives a one-image
reconstruction model the best chance: limb-to-body separation, feet visible, nothing
cropped, even light, no props.

Usage: python generate_hero.py [--out PATH] [--seed N]
"""
import argparse
import json
import time
import urllib.request
from pathlib import Path

from PIL import Image

HOST = "http://127.0.0.1:8188"
COMFY = Path("/Users/dcruse/media-stack/ComfyUI")
CKPT = "flux1-dev-fp8.safetensors"

PROMPT = (
    "full body studio photograph of a young woman, athletic toned build, dark brown "
    "hair in a high messy bun with loose strands, freckles, wearing a dark olive green "
    "tight short sleeved crop top and medium wash blue low rise denim jeans, "
    "standing in a technical reference A-pose, both arms held straight down and "
    "outward away from the body at a forty five degree angle, both hands empty and "
    "open with palms facing the thighs, clear empty space visible between each arm "
    "and the torso, no hand in pockets, no crossed arms, legs straight and shoulder "
    "width apart, both feet flat on the floor and fully visible, facing the camera "
    "at a slight three quarter angle, the entire figure from head to feet inside the "
    "frame with even margin on all sides, plain flat neutral grey seamless studio "
    "background, no props, no furniture, soft even diffused studio lighting with no "
    "hard shadows, matte fabric, eighty five millimeter lens, camera at chest height, "
    "photorealistic, sharp focus, high detail"
)


def api(path, payload=None, timeout=1800):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"{HOST}{path}", data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    return json.loads(raw) if raw else {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/Users/dcruse/media-stack/scratch/hero_apose.png")
    ap.add_argument("--seed", type=int, default=7711)
    ap.add_argument("--width", type=int, default=832)
    ap.add_argument("--height", type=int, default=1216)
    a = ap.parse_args()

    wf = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": CKPT}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": PROMPT, "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["1", 1]}},
        "4": {"class_type": "EmptyLatentImage",
              "inputs": {"width": a.width, "height": a.height, "batch_size": 1}},
        "5": {"class_type": "KSampler",
              "inputs": {"model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0],
                         "latent_image": ["4", 0], "seed": a.seed, "steps": 20,
                         "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple",
                         "denoise": 1.0}},
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage",
              "inputs": {"images": ["6", 0], "filename_prefix": "hero_apose"}},
    }

    t0 = time.time()
    r = api("/prompt", {"prompt": wf})
    pid = r.get("prompt_id")
    if not pid:
        print("[hero] REJECTED:", json.dumps(r)[:800])
        return
    while True:
        time.sleep(5)
        h = api(f"/history/{pid}")
        if pid in h:
            break
    imgs = [i["filename"] for o in h[pid].get("outputs", {}).values()
            for i in o.get("images", [])]
    if not imgs:
        print("[hero] no image produced")
        return
    src = COMFY / "output" / imgs[0]
    Image.open(src).save(a.out)
    print(f"[hero] {time.time()-t0:.0f}s -> {a.out}")


if __name__ == "__main__":
    main()
