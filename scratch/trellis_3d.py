"""TRELLIS 2 image -> 3D with generated PBR, all local.

Three diffusion stages (structure -> shape -> texture), then a real texture bake
from the textured voxel field, UV unwrap, and GLB export. This is the path that
produces *generated* surface detail rather than a projection of one photo.

blender/pig not required. Run:
  python trellis_3d.py front.png [out.glb]
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

UNET = "trellis_2_int8_convrot.safetensors"
CLIP = "dino_v3_vit_l.safetensors"
SHAPE_VAE = "trellis_2_shape_vae_bf16.safetensors"
TEX_VAE = "trellis_2_texture_vae_bf16.safetensors"

SEED = 7
STEPS_STRUCT, STEPS_SHAPE, STEPS_TEX = 12, 20, 12
# 7.5 / 7.5 / 1.0 mirrors the official 3d_pixal3d_trellis2 template: the texture
# stage runs cond-only, guidance comes from the refine pass below.
CFG_STRUCT, CFG_SHAPE, CFG_TEX = 7.5, 7.5, 1.0
STEPS_REFINE, CFG_REFINE = 12, 7.5
# BakeTextureFromVoxel emits THREE images; slot 0 was assumed to be base colour
# and produced flat grey, so make the slot selectable.
TEXSLOT = int(__import__("os").environ.get("TEXSLOT", "0"))
UPSAMPLE = 1536
TEX_SIZE = 2048
DECIMATE = 150000


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
        print(f"\nHTTP {exc.code} from {path}:\n{body[:3000]}\n", file=sys.stderr, flush=True)
        raise


def stage(path: Path) -> str:
    INPUT.mkdir(parents=True, exist_ok=True)
    name = f"trellis_{path.stem}.png"
    shutil.copy(path, INPUT / name)
    return name


def build(image: str, vcol: bool = False) -> dict:
    wf = _base_graph(image)
    if vcol:
        # Vertex-colour path: PaintMesh already carries the textured voxel colours
        # into COLOR_0. The UV bake can produce a corrupted atlas, so keep this as
        # the comparison path.
        wf["20"]["inputs"]["mesh"] = ["18", 0]
        wf["23"] = {"class_type": "SaveGLB",
                    "inputs": {"mesh": ["20", 0], "filename_prefix": "3d/trellis_vcol"}}
        for k in ("19", "21", "22"):
            wf.pop(k, None)
    return wf


def _base_graph(image: str) -> dict:
    return {
        # model
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": UNET, "weight_dtype": "default"}},
        "2": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["1", 0], "shift": 5.0}},
        "3": {"class_type": "CLIPVisionLoader", "inputs": {"clip_name": CLIP}},
        "9": {"class_type": "VAELoader", "inputs": {"vae_name": SHAPE_VAE}},
        "16": {"class_type": "VAELoader", "inputs": {"vae_name": TEX_VAE}},
        # input
        "4": {"class_type": "LoadImage", "inputs": {"image": image}},
        "5": {"class_type": "Trellis2Conditioning",
              "inputs": {"clip_vision_model": ["3", 0], "image": ["4", 0]}},
        # stage 1: structure
        "6": {"class_type": "EmptyTrellis2LatentStructure", "inputs": {"batch_size": 1}},
        "7": {"class_type": "KSampler",
              "inputs": {"model": ["2", 0], "positive": ["5", 0], "negative": ["5", 1],
                         "latent_image": ["6", 0], "seed": SEED, "steps": STEPS_STRUCT,
                         "cfg": CFG_STRUCT, "sampler_name": "euler",
                         "scheduler": "normal", "denoise": 1.0}},
        "8": {"class_type": "VaeDecodeStructureTrellis2",
              "inputs": {"samples": ["7", 0], "vae": ["9", 0], "resolution": "32"}},
        # stage 2: shape
        "10": {"class_type": "Trellis2ShapeStage",
               "inputs": {"positive": ["5", 0], "negative": ["5", 1], "voxel": ["8", 0]}},
        # CFG rescale parity with the reference pipeline. Without it the texture
        # stage collapses to degenerate colour (three runs confirmed).
        "30": {"class_type": "RescaleCFG", "inputs": {"model": ["2", 0], "multiplier": 0.5}},
        "31": {"class_type": "RescaleCFG", "inputs": {"model": ["2", 0], "multiplier": 0.7}},
        "11": {"class_type": "KSampler",
               "inputs": {"model": ["30", 0], "positive": ["10", 0], "negative": ["10", 1],
                          "latent_image": ["10", 2], "seed": SEED + 1, "steps": STEPS_SHAPE,
                          "cfg": CFG_SHAPE, "sampler_name": "euler",
                          "scheduler": "normal", "denoise": 1.0}},
        "12": {"class_type": "VaeDecodeShapeTrellis",
               "inputs": {"samples": ["11", 0], "vae": ["9", 0]}},
        # stage 3: texture
        "13": {"class_type": "Trellis2UpsampleStage",
               "inputs": {"positive": ["10", 0], "negative": ["10", 1],
                          "shape_latent": ["10", 2], "vae": ["9", 0],
                          "target_resolution": UPSAMPLE}},
        # refine pass on the upsampled latent. Feeding the raw upsample straight
        # into the texture stage yields a noise atlas -> scrambled bake.
        "24": {"class_type": "KSampler",
               "inputs": {"model": ["2", 0], "positive": ["13", 0], "negative": ["13", 1],
                          "latent_image": ["13", 2], "seed": SEED, "steps": STEPS_REFINE,
                          "cfg": CFG_REFINE, "sampler_name": "euler",
                          "scheduler": "simple", "denoise": 1.0}},
        "14": {"class_type": "Trellis2TextureStage",
               "inputs": {"positive": ["13", 0], "negative": ["13", 1],
                          "shape_latent": ["24", 0]}},
        "15": {"class_type": "KSampler",
               "inputs": {"model": ["31", 0], "positive": ["14", 0], "negative": ["14", 1],
                          "latent_image": ["14", 2], "seed": SEED + 2, "steps": STEPS_TEX,
                          "cfg": CFG_TEX, "sampler_name": "euler",
                          "scheduler": "normal", "denoise": 1.0}},
        "17": {"class_type": "VaeDecodeTextureTrellis",
               "inputs": {"samples": ["15", 0], "vae": ["16", 0],
                          "shape_subdivides": ["12", 1]}},
        # paint + bake real mappings
        "18": {"class_type": "PaintMesh",
               "inputs": {"mesh": ["12", 0], "voxel_colors": ["17", 0]}},
        # decimate before unwrap: dense meshes explode the chart count and OOM the server
        "20": {"class_type": "DecimateMesh",
               "inputs": {"mesh": ["18", 0], "target_face_count": DECIMATE,
                          "placement_mode": "midpoint"}},
        "21": {"class_type": "UnwrapMesh",
               "inputs": {"mesh": ["20", 0], "segmenter": "pec", "resolution": TEX_SIZE,
                          "padding": 4, "weld_distance": 0.0001}},
        # BakeTextureFromVoxel never unwraps — it bakes onto existing UVs, so it
        # must receive the unwrapped mesh, not the raw painted one.
        "19": {"class_type": "BakeTextureFromVoxel",
               "inputs": {"mesh": ["21", 0], "voxel_colors": ["17", 0],
                          "texture_size": TEX_SIZE}},
        "22": {"class_type": "ApplyTextureToMesh",
               "inputs": {"mesh": ["21", 0], "base_color": ["19", TEXSLOT]}},
        "23": {"class_type": "SaveGLB",
               "inputs": {"mesh": ["22", 0], "filename_prefix": "3d/trellis"}},
    }


def wait_for_idle(timeout_s: int = 1800) -> None:
    """Block until the ComfyUI queue is empty.

    The machine is shared: Dylan drives ComfyUI from the UI, other agents on this
    box queue their own jobs, and two heavy models at once will OOM 64 GB of
    unified memory. Defer to whatever is already running instead of racing it.
    """
    deadline = time.time() + timeout_s
    announced = False
    while time.time() < deadline:
        try:
            q = api("GET", "/queue", timeout=10)
        except Exception:
            time.sleep(3)
            continue
        busy = len(q.get("queue_running") or []) + len(q.get("queue_pending") or [])
        if busy == 0:
            if announced:
                print("queue clear, submitting", flush=True)
            return
        if not announced:
            print(f"ComfyUI busy ({busy} job(s)) — waiting for it to clear...", flush=True)
            announced = True
        time.sleep(5)
    raise SystemExit("gave up waiting for an idle ComfyUI queue")


def main():
    args = sys.argv[1:]
    vcol = "--vcol" in args
    if vcol:
        args.remove("--vcol")
    no_wait = "--now" in args
    if no_wait:
        args.remove("--now")
    if not args:
        sys.exit("usage: trellis_3d.py <image> [out.glb] [--vcol] [--now]")
    src = Path(args[0])
    out = Path(args[1]) if len(args) > 1 else (VR / "pig_trellis.glb")
    if not src.is_file():
        sys.exit(f"missing image: {src}")

    wf = build(stage(src), vcol=vcol)
    if not no_wait:
        wait_for_idle()
    t0 = time.time()
    sub = api("POST", "/prompt", {"prompt": wf, "client_id": uuid.uuid4().hex})
    pid = sub.get("prompt_id")
    print("submitted", pid, flush=True)
    if not pid:
        sys.exit(f"submit failed: {sub}")

    deadline = time.time() + 3600
    entry = None
    while time.time() < deadline:
        time.sleep(3)
        try:
            hist = api("GET", f"/history/{pid}")
        except Exception:
            continue
        if pid in hist:
            entry = hist[pid]
            break
    if entry is None:
        sys.exit("timed out")

    status = entry.get("status") or {}
    if status.get("status_str") == "error":
        print(json.dumps(status, indent=2)[:2500])
        sys.exit("workflow errored")

    files = []
    for node_out in (entry.get("outputs") or {}).values():
        for val in node_out.values():
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, dict) and str(item.get("filename", "")).endswith(".glb"):
                        files.append(item)
    if not files:
        print(json.dumps(entry.get("outputs"), indent=2)[:1500])
        sys.exit("no GLB produced")

    f = files[0]
    produced = OUTPUT / f.get("subfolder", "") / f["filename"]
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(produced, out)
    print(f"done in {time.time()-t0:.1f}s -> {out} ({out.stat().st_size/2**20:.1f} MB)")


if __name__ == "__main__":
    main()
