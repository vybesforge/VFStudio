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
import sys
import time
import urllib.request
from pathlib import Path

COMFY = Path("/Users/dcruse/media-stack/ComfyUI")
HOST = "http://127.0.0.1:8188"

# reuse the UI->API converter from the proven script rather than re-deriving it.
# NOTE: run_trellis2.py parses sys.argv at import time and *deletes* --image/--refname,
# so protect our own argv while importing it.
_saved_argv = list(sys.argv)
sys.argv = [sys.argv[0]]
_spec = importlib.util.spec_from_file_location(
    "rt", "/Users/dcruse/media-stack/scratch/run_trellis2.py")
rt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rt)
sys.argv = _saved_argv

DROP = {"319", "55", "56", "242", "298", "322", "323", "246"}

PROFILES = {
    "default": {},
    # Head-only recon: a bust that fills the frame is the pathological case for the
    # texture stage (400-440 s/step at remesh 1024), so remesh drops to 384 and the
    # decimate budget to 250k. Unwrap 2048 / colour bake 4096 is plenty for a head.
    "head": {
        "312": {"width": 1024, "height": 1024},      # ImageCropToMask
        "94": {"target_resolution": 1536},           # Trellis2UpsampleStage
        "3": {"steps": 20},
        "18": {"steps": 24},
        "23": {"steps": 20},
        "12": {"steps": 20},
        "241": {"resolution": 384},                  # RemeshMesh
        "186": {"target_face_count": 250000},        # DecimateMesh
        "288": {"value": 4096},                      # unwrap res + bake size
        "233": {"resolution": 2048},
        "224": {"resolution": 2048},
        "261": {"resolution": 1024},
    },
    # Cheap head profile: after the 867 s/step swing (10 GB swap in use) the texture
    # stage cost is dominated by the upsample target resolution, so drop it to 1024 and
    # trim the step counts. Use after a full unload.
    "headfast": {
        "312": {"width": 1024, "height": 1024},
        "94": {"target_resolution": 1024},
        "3": {"steps": 16},
        "18": {"steps": 20},
        "23": {"steps": 16},
        "12": {"steps": 16},
        "241": {"resolution": 320},
        "186": {"target_face_count": 250000},
        "288": {"value": 2048},
        "233": {"resolution": 1024},
        "224": {"resolution": 2048},
        "261": {"resolution": 1024},
    },
    # Full-body animal: hq's remesh 1024 / 1.2M faces is what makes the texture stage crawl,
    # so trade a little geometry detail for a faster bake but keep the 4096 atlas — the
    # texture is the whole point of this profile.
    "hog": {
        "312": {"width": 1536, "height": 1536},
        "94": {"target_resolution": 1536},
        "3": {"steps": 20},
        "18": {"steps": 26},
        "23": {"steps": 20},
        "12": {"steps": 28},                          # texture KSampler: more steps, better skin
        "241": {"resolution": 512},
        "186": {"target_face_count": 900000},
        "288": {"value": 4096},
        "233": {"resolution": 2048},
        "224": {"resolution": 4096},
        "261": {"resolution": 2048},
    },
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
        "band": 1.0, "project_back": 0.0, "fix_poles": False,
        "smooth_iters": 20, "drop_small_components": 0.01,
        "precluster_max_verts": 20000000,
        # DynamicCombo: the combo value is the option KEY and the sub-widgets are
        # namespaced inputs ("<combo>.<sub>") — a nested dict instead raises
        # "RemeshMesh.execute() missing 1 required positional argument: 'sign_mode'",
        # and bare sibling keys fail validation. Both end with no GLB and a
        # status_str=success.
        "sign_mode": "solid", "sign_mode.fill": 20.0, "sign_mode.qef": False,
    })
    for _k in ("fill", "qef"):
        p["241"]["inputs"].pop(_k, None)

    for nid in ("186",):
        # DecimateMesh's placement_mode is a DynamicCombo too: same namespaced-input rule.
        # qem keeps feature edges (midpoint is the cheap fallback).
        p[nid]["inputs"].update({
            "placement_mode": "qem",
            "placement_mode.line_quadric_weight": 0.0,
            "placement_mode.feature_edge_quadric_weight": 0.0,
            "placement_mode.feature_edge_min_dihedral_deg": 30.0,
            "placement_mode.clamp_v_to_edge": True,
        })
        p[nid]["inputs"].setdefault("target_face_count",
                                    PROFILES[profile].get("186", {})
                                    .get("target_face_count", 700000))

    for nid in list(p):
        if nid in DROP:
            del p[nid]

    p["900"] = {"class_type": "SaveGLB",
                "inputs": {"mesh": mesh_src, "filename_prefix": prefix},
                "_meta": {"title": "SaveGLB (pepper)"}}

    # nothing may point at a removed node
    # Generic guard: any DynamicCombo left unset fails at *execution* time (after 20+
    # minutes of sampling), so catch it before submitting.
    for nid, node in p.items():
        spec_ = oi.get(node["class_type"], {}).get("input", {})
        for grp in ("required", "optional"):
            for name, meta in spec_.get(grp, {}).items():
                if isinstance(meta, list) and meta and meta[0] == "COMFY_DYNAMICCOMBO_V3":
                    val = node["inputs"].get(name)
                    opts = {o["key"]: list(o["inputs"].get("required", {}))
                            for o in meta[1]["options"]}
                    if val not in opts:
                        raise SystemExit(f"[trellis] {nid} {node['class_type']}.{name} "
                                         f"not set (options {list(opts)})")
                    missing = [s for s in opts[val]
                               if f"{name}.{s}" not in node["inputs"]]
                    if missing:
                        raise SystemExit(f"[trellis] {nid} {node['class_type']}.{name} "
                                         f"missing sub-inputs {missing}")

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

    # The only proof of success is the file on disk: a prompt can report success having
    # executed a preview branch only (validation errors on any branch drop every output
    # node and still return status_str=success).
    folder = COMFY / "output" / "3d"
    hits = sorted(folder.glob("*.glb"), key=lambda f: f.stat().st_mtime, reverse=True) \
        if folder.exists() else []
    if hits:
        newest = hits[0]
        age_min = (time.time() - newest.stat().st_mtime) / 60
        print(f"[trellis] newest GLB {newest.name} ({newest.stat().st_size/1e6:.1f} MB, "
              f"{age_min:.1f} min old)", flush=True)
        if age_min > 10:
            print("[trellis] FAILED: no GLB written by this run", flush=True)
    else:
        print("[trellis] FAILED: no GLB anywhere in output/3d", flush=True)


if __name__ == "__main__":
    main()
