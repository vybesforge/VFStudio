import time

from hermes_cli.plugins import discover_plugins

discover_plugins()

from agent.image_gen_registry import get_active_provider

p = get_active_provider()

for model, label in (("sd_xl_base_1.0.safetensors", "SDXL"),
                     ("flux1-dev-fp8.safetensors", "FLUX")):
    t = time.time()
    r = p.generate(
        "a weathered brass diving helmet on a wooden dock, moody overcast light",
        aspect_ratio="square",
        model=model,
    )
    dt = time.time() - t
    print(f"{label}: {dt:.1f}s  success={r.get('success')}  {r.get('image')}", flush=True)
