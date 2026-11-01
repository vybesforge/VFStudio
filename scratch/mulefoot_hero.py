"""Mulefoot hog: hero reference candidates at 1024x1024.

Breed-accurate prompt matters here. The Mulefoot's defining trait is a FUSED,
uncloven single hoof (syndactyly) — a generic pig prompt renders cloven toes and
loses the only thing that makes the breed the breed.

Run: python mulefoot_hero.py
"""
import json
import time

from hermes_cli.plugins import discover_plugins

discover_plugins()

from agent.image_gen_registry import get_active_provider

p = get_active_provider()

PROMPT = (
    "photorealistic American Mulefoot hog standing broadside in profile facing left, "
    "solid charcoal-black skin with short glossy bristled hair, "
    "distinctive single FUSED mule-like hooves with no cloven split, "
    "long snout tapering downward, semi-floppy ears pricked forward, boar-like face, "
    "stocky medium-large body, muscular shoulders and heavy hindquarters, "
    "full body from snout tip to tail in frame with margin, whole animal visible, "
    "plain seamless light grey studio background, soft even diffuse lighting, "
    "no cast shadow, extremely detailed skin and bristle texture, "
    "wildlife photography, sharp focus, 8k"
)

# NB: Flux dev is guidance-distilled (cfg 1.0) so a negative prompt is ignored —
# the framing and "no shadow" instruction have to live in the positive prompt.

out = []
for i, seed in enumerate((8801, 8802, 8803, 8804)):
    t = time.time()
    r = p.generate(PROMPT, aspect_ratio="square", model="flux1-dev-fp8.safetensors", seed=seed)
    out.append({"seed": seed, "ok": r.get("success"), "file": r.get("image"),
                "secs": round(time.time() - t, 1)})
    print(i, out[-1], flush=True)

print(json.dumps(out, indent=2))
