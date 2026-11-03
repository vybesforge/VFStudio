"""Try to force true extreme camera angles out of the Qwen edit + Multiple-angles LoRA.

The batch prompts "camera on the floor at her feet looking up" and got an eye-level shot
back, so the wording matters more than the LoRA alone. Each variant is one 4-step job.
"""
import importlib.util
import sys
import time
from pathlib import Path

from PIL import Image

_spec = importlib.util.spec_from_file_location(
    "pa", "/Users/dcruse/media-stack/scratch/pp_angles.py")
pa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pa)

COMFY = Path("/Users/dcruse/media-stack/ComfyUI")
OUT = Path("/Users/dcruse/media-stack/output/image/pepper_camtest")
OUT.mkdir(parents=True, exist_ok=True)

BASE = ("Same woman: warm tan olive skin, athletic toned build, dark brown hair in a high "
        "messy bun, olive-green ribbed crop top, blue jeans.")

VARIANTS = [
    ("worm_1",
     "EXTREME WORM'S-EYE VIEW: the camera lens is lying on the studio floor between her feet "
     "and points straight up her body. Her bare feet and toes fill the bottom of the frame and "
     "loom huge, her legs recede, her torso is seen from underneath, her chin and the underside "
     "of her jaw are visible above, her head is tiny and far away at the top. Strong upward "
     "perspective, 18mm ultra wide angle, converging verticals."),
    ("worm_2",
     "Very low camera placed on the floor at her feet, tilted up forty five degrees so the shot "
     "looks up at her from below. Her feet are the largest thing in the frame, her legs "
     "foreshorten dramatically, we see the soles of her feet and the underside of her chin. "
     "Upward perspective distortion, wide lens."),
    ("overhead_1",
     "Directly overhead bird's-eye view: the camera is mounted on the ceiling pointing straight "
     "down at her. We see the top of her hair bun, her forehead and nose foreshortened, her "
     "shoulders, the tops of her arms and the floor spread around her feet. Circular top-down "
     "perspective, no horizon line."),
]

for name, cam in VARIANTS:
    prompt = (f"{cam} {BASE} Plain flat neutral light grey seamless studio floor and background, "
              f"no props, soft even studio lighting, photorealistic, sharp focus.")
    if not pa.wait_idle():
        sys.exit("queue busy")
    wf = pa.build("pp_angle_master.png", prompt, 4, 1.0, 9001, 832, 1248,
                  loras=[(pa.MULTI_LORA, 1.0), (pa.LIGHTNING, 1.0)])
    t0 = time.time()
    r = pa.api("/prompt", {"prompt": wf})
    pid = r.get("prompt_id")
    if not pid:
        print(name, "REJECTED", str(r)[:400]); continue
    while True:
        time.sleep(5)
        h = pa.api(f"/history/{pid}")
        if pid in h:
            break
    imgs = [i["filename"] for o in h[pid].get("outputs", {}).values()
            for i in o.get("images", [])]
    if not imgs:
        print(name, "no image"); continue
    dest = OUT / f"pepper_{name}.png"
    Image.open(COMFY / "output" / imgs[0]).save(dest)
    print(f"{name}: {time.time()-t0:.0f}s -> {dest}", flush=True)
