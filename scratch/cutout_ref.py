"""Cut the studio background out of a reference image before meshing.

Why this exists: image-to-3D reconstructs the *background* as geometry. Our last
pig came back with a flat slab fused to its feet (24% of vertices in the bottom
5% of its height) because the reference had a plain studio backdrop. Removing
the background first is the root-cause fix; trimming the pedestal afterwards is
not.

Runs BiRefNet inside ComfyUI, composites the subject onto pure white, and saves
a tightly framed cutout.

  python cutout_ref.py in.png out.png [--pad 0.04]
"""

import json
import shutil
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

COMFY = Path.home() / "media-stack" / "ComfyUI"
INPUT = COMFY / "input"
OUTPUT = COMFY / "output"
BASE = "http://127.0.0.1:8188"
BG_MODEL = "birefnet.safetensors"


def api(method, path, payload=None, timeout=60):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        f"{BASE}{path}", data=data, method=method,
        headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        print(f"\nHTTP {exc.code} {path}:\n{body[:2000]}\n", file=sys.stderr, flush=True)
        raise


def build(image_name: str) -> dict:
    # 1 = subject stays, 0 = background replaced with the white destination
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "2": {"class_type": "LoadBackgroundRemovalModel",
              "inputs": {"bg_removal_name": BG_MODEL}},
        "3": {"class_type": "RemoveBackground",
              "inputs": {"bg_removal_model": ["2", 0], "image": ["1", 0]}},
        "4": {"class_type": "EmptyImage",
              "inputs": {"width": 1024, "height": 1024, "batch_size": 1, "color": 0xFFFFFF}},
        "5": {"class_type": "ImageCompositeMasked",
              "inputs": {"destination": ["4", 0], "source": ["1", 0],
                         "x": 0, "y": 0, "resize_source": True, "mask": ["3", 0]}},
        "6": {"class_type": "SaveImage",
              "inputs": {"images": ["5", 0], "filename_prefix": "cutout"}},
    }


def main():
    args = [a for a in sys.argv[1:]]
    if len(args) < 2:
        sys.exit("usage: cutout_ref.py in.png out.png")
    src, dst = Path(args[0]), Path(args[1])
    if not src.is_file():
        sys.exit(f"missing image: {src}")

    INPUT.mkdir(parents=True, exist_ok=True)
    staged = f"cutout_in_{src.stem}.png"
    shutil.copy(src, INPUT / staged)

    # never race another job on the shared box
    deadline = time.time() + 900
    while time.time() < deadline:
        q = api("GET", "/queue", timeout=10)
        if not (q.get("queue_running") or q.get("queue_pending")):
            break
        time.sleep(5)

    t0 = time.time()
    sub = api("POST", "/prompt", {"prompt": build(staged), "client_id": uuid.uuid4().hex})
    pid = sub.get("prompt_id")
    print("submitted", pid, flush=True)

    while time.time() < deadline:
        time.sleep(2)
        try:
            hist = api("GET", f"/history/{pid}")
        except Exception:
            continue
        if pid in hist:
            entry = hist[pid]
            break
    else:
        sys.exit("timed out")

    status = entry.get("status") or {}
    if status.get("status_str") == "error":
        print(json.dumps(status, indent=2)[:1500])
        sys.exit("cutout workflow errored")

    files = []
    for node_out in (entry.get("outputs") or {}).values():
        for val in node_out.values():
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, dict) and item.get("filename"):
                        files.append(item)
    if not files:
        sys.exit("no image produced")

    f = files[0]
    produced = OUTPUT / f.get("subfolder", "") / f["filename"]
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(produced, dst)
    print(f"cutout in {time.time()-t0:.1f}s -> {dst} ({dst.stat().st_size/1024:.0f} KB)")


if __name__ == "__main__":
    main()
