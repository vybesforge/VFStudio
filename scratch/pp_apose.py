"""Pepper hero photo -> full-body A-pose reference via Qwen-Image-Edit 2509 (GGUF).

Same graph as ComfyUI's official image_qwen_image_edit_2509 template:
  FluxKontextImageScale on the reference -> TextEncodeQwenImageEditPlus(image1+vae)
  -> VAEEncode latent -> KSampler denoise 1.0 -> CFGNorm / ModelSamplingAuraFlow(3).

Differences from scratch/qwen_apose.py:
  * Q4_K_M GGUF unet (UnetLoaderGGUF) instead of the fp8 safetensors: fp8 has no MPS
    kernel, ComfyUI upcasts it to bf16 (39 GB) and swaps.
  * explicit target canvas size so the output stays 2:3 portrait (full body) rather
    than whatever FluxKontextImageScale picks.

  python pp_apose.py --image /Users/dcruse/Documents/ppimage.png --out OUT.png \
      --seed 5150 --steps 20 --cfg 2.5 --size 832x1248
"""
import argparse
import json
import time
import urllib.request
from pathlib import Path

from PIL import Image

HOST = "http://127.0.0.1:8188"
COMFY = Path("/Users/dcruse/media-stack/ComfyUI")

UNET = "Qwen-Image-Edit-2509-Q4_K_M.gguf"
CLIP = "qwen_2.5_vl_7b_fp8_scaled.safetensors"
VAE = "qwen_image_vae.safetensors"
LIGHTNING = "Qwen-Image-Edit-2509-Lightning-4steps-V1.0-bf16.safetensors"

PROMPT = (
    "Show the exact same woman as a full body studio photograph from head to feet. "
    "Keep her identity completely unchanged: warm medium tan olive skin, athletic "
    "toned build with defined abdominal muscles, dark brown hair in a high messy "
    "top-knot bun with loose strands framing her face, dark brown eyes, thick dark "
    "eyebrows, small mole on her left cheek, small silver navel piercing. She wears "
    "the same tight olive-green ribbed short-sleeve crop top and the same mid-rise "
    "blue denim jeans. She stands in a clean technical A-pose: both arms straight "
    "and angled thirty to forty degrees away from her torso with clear empty space "
    "between each arm and her body, open relaxed hands, legs straight and slightly "
    "apart, both bare feet flat on the floor and fully visible. The entire figure "
    "including the top of her bun and her feet is inside the frame with even margin. "
    "Plain flat neutral light grey seamless studio background, no props, soft even "
    "diffused studio lighting, matte surfaces, eighty five millimetre lens, camera "
    "at chest height, photorealistic, sharp focus, high detail."
)


def api(path, payload=None, timeout=1800):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"{HOST}{path}", data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    return json.loads(raw) if raw else {}


def wait_idle(give_up=3600):
    t0 = time.time()
    while time.time() - t0 < give_up:
        q = api("/queue")
        if not q.get("queue_running") and not q.get("queue_pending"):
            return True
        time.sleep(5)
    return False


def build(image_name, prompt, steps, cfg, seed, width, height, lora=None,
          lora_strength=1.0, negative=""):
    wf = {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": UNET}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": CLIP, "type": "qwen_image", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "4": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "5": {"class_type": "FluxKontextImageScale", "inputs": {"image": ["4", 0]}},
        "15": {"class_type": "ImageScale",
               "inputs": {"image": ["5", 0], "upscale_method": "lanczos",
                          "width": width, "height": height, "crop": "disabled"}},
        "6": {"class_type": "TextEncodeQwenImageEditPlus",
              "inputs": {"clip": ["2", 0], "prompt": prompt, "vae": ["3", 0],
                         "image1": ["15", 0]}},
        "7": {"class_type": "TextEncodeQwenImageEditPlus",
              "inputs": {"clip": ["2", 0], "prompt": negative, "vae": ["3", 0],
                         "image1": ["15", 0]}},
        "8": {"class_type": "ModelSamplingAuraFlow",
              "inputs": {"model": ["1", 0], "shift": 3.0}},
        "9": {"class_type": "CFGNorm",
              "inputs": {"model": ["8", 0], "strength": 1.0, "pre_cfg": False}},
        "10": {"class_type": "VAEEncode", "inputs": {"pixels": ["15", 0], "vae": ["3", 0]}},
        "11": {"class_type": "KSampler",
               "inputs": {"model": ["9", 0], "positive": ["6", 0], "negative": ["7", 0],
                          "latent_image": ["10", 0], "seed": seed, "steps": steps,
                          "cfg": cfg, "sampler_name": "euler", "scheduler": "simple",
                          "denoise": 1.0}},
        "12": {"class_type": "VAEDecode", "inputs": {"samples": ["11", 0], "vae": ["3", 0]}},
        "13": {"class_type": "SaveImage",
               "inputs": {"images": ["12", 0], "filename_prefix": "pp_apose"}},
    }
    if lora:
        wf["14"] = {"class_type": "LoraLoaderModelOnly",
                    "inputs": {"model": ["1", 0], "lora_name": lora,
                               "strength_model": lora_strength}}
        wf["8"]["inputs"]["model"] = ["14", 0]
    return wf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default="/Users/dcruse/Documents/ppimage.png")
    ap.add_argument("--out", default="/Users/dcruse/media-stack/output/image/pepper_apose.png")
    ap.add_argument("--steps", type=int, default=20)
    ap.add_argument("--cfg", type=float, default=2.5)
    ap.add_argument("--seed", type=int, default=5150)
    ap.add_argument("--size", default="832x1248")
    ap.add_argument("--prompt", default=PROMPT)
    ap.add_argument("--negative", default="")
    ap.add_argument("--fast", action="store_true", help="Lightning 4-step LoRA")
    ap.add_argument("--now", action="store_true")
    a = ap.parse_args()

    staged = COMFY / "input" / "pp_apose_src.png"
    Image.open(a.image).convert("RGB").save(staged)
    w, h = (int(v) for v in a.size.lower().split("x"))
    steps, cfg, lora = (4, 1.0, LIGHTNING) if a.fast else (a.steps, a.cfg, None)
    print(f"[pp] staged {a.image} -> {staged} size={w}x{h} steps={steps} cfg={cfg} "
          f"seed={a.seed} fast={a.fast}", flush=True)

    if not a.now and not wait_idle():
        print("[pp] queue never drained")
        return
    t0 = time.time()
    wf = build("pp_apose_src.png", a.prompt, steps, cfg, a.seed, w, h, lora=lora,
               negative=a.negative)
    r = api("/prompt", {"prompt": wf})
    pid = r.get("prompt_id")
    if not pid:
        print("[pp] REJECTED:", json.dumps(r)[:1200])
        return
    while True:
        time.sleep(5)
        hz = api(f"/history/{pid}")
        if pid in hz:
            break
        el = time.time() - t0
        if el > 3600:
            print("[pp] timeout")
            return
        if int(el) % 60 < 5:
            try:
                st = api("/prompt").get("exec_info", {}).get("queue_remaining")
            except Exception:
                st = "?"
            print(f"[pp] {el:.0f}s queue_remaining={st}", flush=True)
    entry = hz[pid]
    st = entry.get("status", {})
    if st.get("status_str") == "error":
        for m in st.get("messages", []):
            if m and m[0] == "execution_error":
                print("[pp] ERROR:", json.dumps(m[1])[:800])
    imgs = [i["filename"] for o in entry.get("outputs", {}).values()
            for i in o.get("images", [])]
    if not imgs:
        print("[pp] no image")
        return
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    Image.open(COMFY / "output" / imgs[0]).save(out)
    print(f"[pp] {time.time()-t0:.0f}s -> {out}", flush=True)


if __name__ == "__main__":
    main()
