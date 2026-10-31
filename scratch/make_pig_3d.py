"""Image(s) -> textured-free 3D mesh (GLB) using local Hunyuan3D 2.1 in ComfyUI.

Uses the 4-view conditioning path, which gives much better geometry than a single view.
Run:  python make_pig_3d.py front.png right.png back.png left.png
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
VR = Path.home() / "media-stack" / "vr"
BASE = "http://127.0.0.1:8188"
CKPT = "hunyuan_3d_v2.1.safetensors"


def api(method, path, payload=None, timeout=60):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        f"{BASE}{path}", data=data, method=method,
        headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as exc:
        # ComfyUI's node_errors name the exact failing input — always surface it.
        body = exc.read().decode(errors="replace")
        print(f"\nHTTP {exc.code} from {path}:\n{body[:3000]}\n", file=sys.stderr, flush=True)
        raise


def stage(path: Path) -> str:
    """Copy an image into ComfyUI's input dir; LoadImage only reads from there."""
    INPUT.mkdir(parents=True, exist_ok=True)
    name = f"pig_{path.stem}.png"
    shutil.copy(path, INPUT / name)
    return name


def build(images, seed=42, texture=None, unwrap=True, octree=256, decimate=0):
    """images: staged filenames (1 = single-view, 4 = multi-view).
    texture: optional staged filename used as the mesh base colour.
    unwrap: UV-unwrap before texturing (expensive; OOM risk on dense meshes).
    octree: surface resolution — higher is denser and heavier."""
    wf = {
        "1": {"class_type": "ImageOnlyCheckpointLoader",
              "inputs": {"ckpt_name": CKPT}},
    }
    # One CLIPVisionEncode per input view.
    vision_ids = []
    for i, name in enumerate(images):
        img_id, vis_id = str(100 + i * 2), str(101 + i * 2)
        wf[img_id] = {"class_type": "LoadImage", "inputs": {"image": name}}
        wf[vis_id] = {"class_type": "CLIPVisionEncode",
                      "inputs": {"clip_vision": ["1", 1], "image": [img_id, 0],
                                 "crop": "center"}}
        vision_ids.append(vis_id)

    if len(vision_ids) == 1:
        wf["10"] = {"class_type": "Hunyuan3Dv2Conditioning",
                    "inputs": {"clip_vision_output": [vision_ids[0], 0]}}
    else:
        # front, right, back, left — order matters
        slots = ["front", "right", "back", "left"]
        wf["10"] = {"class_type": "Hunyuan3Dv2ConditioningMultiView",
                    "inputs": {slot: [vid, 0] for slot, vid in zip(slots, vision_ids)}}

    wf["11"] = {"class_type": "EmptyLatentHunyuan3Dv2",
                "inputs": {"resolution": 3072, "batch_size": 1}}
    wf["12"] = {"class_type": "KSampler",
                "inputs": {"model": ["1", 0], "positive": ["10", 0], "negative": ["10", 1],
                           "latent_image": ["11", 0], "seed": seed, "steps": 20, "cfg": 8.0,
                           "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0}}
    wf["13"] = {"class_type": "VAEDecodeHunyuan3D",
                "inputs": {"samples": ["12", 0], "vae": ["1", 2],
                           "num_chunks": 8000, "octree_resolution": octree}}
    wf["14"] = {"class_type": "VoxelToMesh",
                "inputs": {"voxel": ["13", 0], "algorithm": "surface net", "threshold": 0.6}}

    mesh_src = ["14", 0]
    if decimate:
        # Decimate BEFORE unwrap: a 500k-tri mesh explodes into ~380k UV charts
        # and OOMs the server. Decimating also makes the asset VR-friendly.
        wf["19"] = {"class_type": "DecimateMesh",
                    "inputs": {"mesh": ["14", 0], "target_face_count": decimate,
                               "placement_mode": "midpoint"}}
        mesh_src = ["19", 0]

    if texture:
        # UV unwrap, then bake the reference image as base colour so the GLB
        # carries skin instead of arriving as bare geometry.
        wf["18"] = {"class_type": "LoadImage", "inputs": {"image": texture}}
        if unwrap:
            wf["16"] = {"class_type": "UnwrapMesh",
                        "inputs": {"mesh": mesh_src, "segmenter": "pec",
                                   "resolution": 2048, "padding": 4, "weld_distance": 0.0001}}
            tex_in = ["16", 0]
        else:
            tex_in = mesh_src
        wf["17"] = {"class_type": "ApplyTextureToMesh",
                    "inputs": {"mesh": tex_in, "base_color": ["18", 0]}}
        mesh_src = ["17", 0]

    wf["15"] = {"class_type": "SaveGLB",
                "inputs": {"mesh": mesh_src, "filename_prefix": "3d/pig"}}
    return wf


def main():
    args = [a for a in sys.argv[1:]]
    texture = None
    unwrap = True
    octree = 256
    decimate = 0
    if "--no-unwrap" in args:
        args.remove("--no-unwrap")
        unwrap = False
    if "--octree" in args:
        i = args.index("--octree")
        octree = int(args[i + 1])
        del args[i:i + 2]
    if "--texture" in args:
        i = args.index("--texture")
        texture = Path(args[i + 1])
        del args[i:i + 2]
    if "--decimate" in args:
        i = args.index("--decimate")
        decimate = int(args[i + 1])
        del args[i:i + 2]

    paths = [Path(p) for p in args[:4]]
    if len(paths) not in (1, 4):
        sys.exit("usage: make_pig_3d.py [--texture tex.png] <one image>  |  front right back left")
    missing = [str(p) for p in paths if not p.is_file()]
    if texture is not None and not texture.is_file():
        missing.append(str(texture))
    if missing:
        sys.exit("missing images: " + ", ".join(missing))

    staged = [stage(p) for p in paths]
    tex_staged = stage(texture) if texture is not None else None
    wf = build(staged, texture=tex_staged, unwrap=unwrap, octree=octree, decimate=decimate)

    t0 = time.time()
    sub = api("POST", "/prompt", {"prompt": wf, "client_id": uuid.uuid4().hex})
    pid = sub.get("prompt_id")
    print("submitted", pid, flush=True)
    if not pid:
        sys.exit(f"submit failed: {sub}")

    deadline = time.time() + 1800
    entry = None
    while time.time() < deadline:
        time.sleep(2)
        try:
            hist = api("GET", f"/history/{pid}")
        except Exception:
            continue
        if pid in hist:
            entry = hist[pid]
            break
    if entry is None:
        sys.exit("timed out waiting for the 3D job")

    status = entry.get("status") or {}
    if status.get("status_str") == "error":
        print(json.dumps(status, indent=2)[:1500])
        sys.exit("workflow errored")

    # SaveGLB files show up under outputs -> any node -> "3d"/"glb"/"mesh" lists
    files = []
    for node_out in (entry.get("outputs") or {}).values():
        for key, val in node_out.items():
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, dict) and str(item.get("filename", "")).endswith((".glb", ".gltf")):
                        files.append(item)
    if not files:
        print(json.dumps(entry.get("outputs"), indent=2)[:1500])
        sys.exit("no GLB in outputs")

    f = files[0]
    src = OUTPUT / f.get("subfolder", "") / f["filename"]
    VR.mkdir(parents=True, exist_ok=True)
    dst = VR / "pig.glb"
    shutil.copy(src, dst)
    print(f"done in {time.time()-t0:.1f}s -> {dst} ({dst.stat().st_size/1048576:.1f} MB)")


if __name__ == "__main__":
    main()
