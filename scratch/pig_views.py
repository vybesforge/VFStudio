"""Generate a consistent multi-view turnaround of a realistic pig for 3D reconstruction."""
import json
import time

from hermes_cli.plugins import discover_plugins

discover_plugins()

from agent.image_gen_registry import get_active_provider

p = get_active_provider()

BASE = ("photorealistic adult domestic pig, pink skin with coarse bristles, standing on all fours, "
        "full body visible head to tail, studio product photography, soft even lighting, "
        "plain seamless white background, no shadow on floor, {view}")

VIEWS = {
    "front": "front view facing camera",
    "side": "perfect side profile view, facing right",
    "back": "rear view from behind",
    "threequarter": "three-quarter front view from the left",
}

out = {}
for name, view in VIEWS.items():
    t = time.time()
    r = p.generate(BASE.format(view=view), aspect_ratio="square",
                   model="flux1-dev-fp8.safetensors", seed=20261030)
    out[name] = {"ok": r.get("success"), "file": r.get("image"), "secs": round(time.time() - t, 1)}
    print(name, out[name], flush=True)

print(json.dumps(out, indent=2))
