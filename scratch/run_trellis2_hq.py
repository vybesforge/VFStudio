"""TRELLIS.2 HQ image->3D through the ComfyUI HTTP API (no browser needed).

The shipped template cannot be queued as-is: `Save3DAdvanced`/`Preview3DAdvanced` need a
`viewport_state` socket that only the web frontend injects, and nothing else in the graph
accepts a MESH output, so a naive prompt reports success having written no file.

Fix: the template's `MeshToFile3D` node already emits FILE_3D_GLB, and `SaveGLB` accepts
that type. So we keep the authored graph untouched (CFGOverride / RescaleCFG / the second
upsample KSampler that the texture stage depends on), swap the viewer nodes for a SaveGLB,
and drop the uninstalled Pixal3D/MoGe branch.

Profile knobs are set by node id — see the table in the local-media-stack skill.

  python run_trellis2_hq.py --image reference.png --prefix 3d/pepper_hq [--profile hq|default]
"""
import argparse
import importlib.util
import json
import time
import urllib.request
from pathlib import Path

COMFY = Path("/Users/dcruse/media-stack/ComfyUI")
HOST = "http://127.0.0.1:8188"

# reuse the UI->API converter from the proven script rather than re-deriving it
_spec = importlib.util.spec_from_file_location(
    "rt", "/Users/dcruse/media-stack/scratch/run_trellis2.py")
rt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rt)

DROP = {"319", "55", "56", "242", "298", "322", "323", "246"}

PROFILES = {
    "default": {},
    "hq": {
        "312": {"width": 1536, "height": 1536},      # ImageCropToMask
        "94": {"target_resolution": 2048},           # Trellis2UpsampleStage
        "3": {"steps": 20},                          # structure KSampler
        "18": {"steps": 28},                         # structure refine KSampler
        "23": {"steps": 20},                         # upsample refine KSampler
        "12": {"steps": 20},                         # texture KSampler
        "241": {"resolution": 1024},                 # RemeshMesh
        "186": {"target_face_count": 1200000},       # DecimateMesh
        "288": {"value": 4096},                      # PrimitiveInt -> unwrap res + bake size
        "233": {"resolution": 2048},                 # BakeAmbientOcclusion
        "224": {"resolution": 4096},                 # BakeNormalMapFromMesh
        "261": {"resolution": 2048},                 # RenderUVAtlas
    },
}


def api(path, payload=None, timeout=120):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"{HOST}{path}", data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    return json.loads(raw) if raw else {}


def build(image_name, prefix, profile):
    oi = rt.load_object_info()
    ui = json.loads(rt.TEMPLATE.read_text())
    for n in rt.find_node_by_type(ui, "PrimitiveBoolean"):
        n["widgets_values"] = [True]                     # TRELLIS.2, not Pixal3D
    for n in rt.find_node_by_type(ui, "LoadImage"):
        n["widgets_values"] = [image_name, "image"]
    for n in rt.find_node_by_type(ui, "PrimitiveInt"):
        n["widgets_values"] = [1536, "fixed"]

    p = rt.convert(ui, oi)

    # the mesh Save3DAdvanced would have received
    mesh_src = p["322"]["inputs"]["model_3d"]

    for nid, over in PROFILES[profile].items():
        if nid in p:
            p[nid]["inputs"].update(over)

    # RemeshMesh's sign_mode is a dynamic combo whose sub-widgets shift positional
    # values; write the base inputs explicitly (same fix as run_trellis2.py).
    p["241"]["inputs"].update({
        "resolution": PROFILES[profile].get("241", {}).get("resolution", 768),
        "sign_mode": "solid", "band": 1.0, "project_back": 0.0, "fix_poles": False,
        "smooth_iters": 20, "drop_small_components": 0.01,
        "precluster_max_verts": 20000000,
    })

    for nid in list(p):
        if nid in DROP:
            del p[nid]

    p["900"] = {"class_type": "SaveGLB",
                "inputs": {"mesh": mesh_src, "filename_prefix": prefix},
                "_meta": {"title": "SaveGLB (pepper)"}}

    # nothing may point at a removed node
    for nid, node in p.items():
        for k, v in list(node["inputs"].items()):
            if isinstance(v, list) and len(v) == 2 and str(v[0]) not in p:
                del node["inputs"][k]
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--prefix", default="3d/pepper_hq")
    ap.add_argument("--profile", default="hq", choices=list(PROFILES))
    ap.add_argument("--now", action="store_true")
    a = ap.parse_args()

    staged = COMFY / "input" / "trellis_input.png"
    from PIL import Image
    Image.open(a.image).convert("RGB").save(staged)
    print(f"[trellis] staged {a.image} -> {staged}", flush=True)

    if not a.now:
        t0 = time.time()
        while time.time() - t0 < 7200:
            q = api("/queue")
            if not q.get("queue_running") and not q.get("queue_pending"):
                break
            time.sleep(10)

    p = build("trellis_input.png", a.prefix, a.profile)
    Path("/Users/dcruse/media-stack/scratch/trellis2_hq_prompt.json").write_text(
        json.dumps(p, indent=1))
    print(f"[trellis] {len(p)} nodes, profile={a.profile}", flush=True)

    r = api("/prompt", {"prompt": p})
    pid = r.get("prompt_id")
    if not pid:
        print("[trellis] REJECTED:", json.dumps(r)[:2000])
        return
    print(f"[trellis] prompt_id={pid}", flush=True)

    t0 = time.time()
    while True:
        time.sleep(15)
        h = api(f"/history/{pid}")
        if pid in h:
            break
        el = time.time() - t0
        if el > 9000:
            print("[trellis] timeout waiting")
            return
        if int(el) % 120 < 15:
            print(f"[trellis] {el/60:.1f} min", flush=True)

    st = h[pid].get("status", {})
    print(f"[trellis] status={st.get('status_str')} in {(time.time()-t0)/60:.1f} min",
          flush=True)
    if st.get("status_str") == "error":
        for m in st.get("messages", []):
            if m and m[0] in ("execution_error", "execution_interrupted"):
                print("[trellis] ERROR:", json.dumps(m[1])[:900])
    outs = h[pid].get("outputs", {})
    print("[trellis] outputs:", json.dumps(outs)[:600], flush=True)


if __name__ == "__main__":
    main()
