"""One hero reference for single-view 3D: adult pig, side-on, clean silhouette."""
from hermes_cli.plugins import discover_plugins

discover_plugins()

from agent.image_gen_registry import get_active_provider

p = get_active_provider()

PROMPT = (
    "photorealistic large adult domestic pig, heavy muscular body, coarse pale pink bristles "
    "with dark patches, standing on all four legs in a perfect side profile facing left, "
    "snout and curly tail fully visible, whole body in frame with margin around it, "
    "seamless pure white studio background, soft even diffuse lighting, no cast shadow, "
    "extremely detailed skin texture, wildlife photography quality, 8k"
)

for i, seed in enumerate((771, 772)):
    r = p.generate(PROMPT, aspect_ratio="landscape",
                   model="flux1-dev-fp8.safetensors", seed=seed)
    print(i, r.get("success"), r.get("image"), flush=True)
