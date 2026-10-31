import json
import time

from hermes_cli.plugins import discover_plugins

discover_plugins()

from agent.image_gen_registry import get_active_provider

p = get_active_provider()
print("provider:", p.name if p else None)
t0 = time.time()
res = p.generate(
    "a 1970s rally car sliding through a forest stage at dusk, dust and headlights, 35mm film grain",
    aspect_ratio="landscape",
    model="flux1-dev-fp8.safetensors",
)
print(f"elapsed: {time.time() - t0:.1f}s")
print(json.dumps({k: v for k, v in res.items() if k != "prompt"}, indent=2)[:1200])
