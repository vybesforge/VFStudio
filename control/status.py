"""Pretty-print media-stack status from the panel API (stdin JSON)."""
import json
import sys

d = json.load(sys.stdin)
for key, v in d["services"].items():
    state = "running" if v["responding"] else ("starting" if v["running"] else "stopped")
    print(f"  {v['label']:<12} :{v['port']}  {state}")

print()
ckpts = d["models"]["comfy"]["checkpoints"]
print("  checkpoints:", ", ".join(ckpts) if ckpts else "(none)")
audio = ", ".join(m["label"] + ("*" if m["cached"] else "") for m in d["models"]["audio"])
print("  audio models:", audio)
print("  (* = already downloaded)")
