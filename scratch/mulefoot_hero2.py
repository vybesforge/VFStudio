"""Mulefoot retry: the fused hoof has to be described by analogy.

Flux ignored "fused/no cloven split" and drew ordinary pig feet on all four first
candidates (confirmed by zooming on the feet, not by looking at the whole body).
Positive analogy phrasing — a horse's hoof — is what actually moves it.

Run: python mulefoot_hero2.py
"""
import json
import time

from hermes_cli.plugins import discover_plugins

discover_plugins()

from agent.image_gen_registry import get_active_provider

p = get_active_provider()

PROMPT = (
    "photorealistic American Mulefoot hog standing broadside in profile facing left, "
    "solid charcoal-black bristled hide, coarsely haired mane along the spine, "
    "long snout tapering downward with a boar-like face, "
    "semi-floppy ears pricked forward, stocky heavy body, "
    "the feet end in SINGLE SOLID HORSE-LIKE HOOVES, one continuous unbroken horn-like hoof "
    "on every leg exactly like a horse's hoof, absolutely no cleft, no split, no two-toed feet, "
    "the whole animal from snout tip to tail is inside the frame with clear margin, "
    "isolated on a clean bright white seamless background, subject cut out, "
    "no ground shadow, no floor, soft even studio light on the animal only, "
    "extremely detailed black bristle and skin texture, sharp focus, wildlife photography"
)

out = []
for i, seed in enumerate((9901, 9902)):
    t = time.time()
    r = p.generate(PROMPT, aspect_ratio="square", model="flux1-dev-fp8.safetensors", seed=seed)
    out.append({"seed": seed, "ok": r.get("success"), "file": r.get("image"),
                "secs": round(time.time() - t, 1)})
    print(i, out[-1], flush=True)

print(json.dumps(out, indent=2))
