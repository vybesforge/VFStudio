"""Run the OFFICIAL Trellis.2 image->3D workflow (as shipped by ComfyUI).

Hand-building this graph from /object_info gets the guidance plumbing wrong:
the template routes the UNET through CFGOverride + RescaleCFG for the structure
and shape stages, refines the upsampled latent with a second KSampler, and feeds
*that* refined latent to the texture stage. Skip any of it and the texture
decode is noise, which bakes into a scrambled atlas.

So: read the shipped template, convert UI-format nodes -> API format prompts,
collapse the Pixal3D/Trellis switches onto the Trellis branch, prune anything
not reachable from the output node, swap in our image, submit.

    python trellis2_official.py <image.png> [out.glb]
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
TEMPLATE = (COMFY / ".venv/lib/python3.12/site-packages"
            / "comfyui_workflow_templates_json/templates"
            / "3d_pixal3d_trellis2_image_to_model.json")

# the official template ships one graph with Pixal3D and Trellis.2 side by side
# behind boolean switches. We force the Trellis.2 branch.
TRELLIS_SWITCHES = {"314": 1, "315": 1, "318": 1}
MESH_OUT = "260"   # MeshSmoothNormals, last mesh node before the file writers
OUTPUT_NODE = "900"   # synthetic SaveGLB we add after pruning

# template ships 700k faces / a 4096 atlas. Both are needless for a VR asset and
# 4096 unwrap on a dense mesh is what OOMs the server, so scale them down.
DECIMATE_FACES = 200000
ATLAS = 2048
SEED_VALUES = {"fixed", "randomize", "increment", "decrement"}
WIDGET_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN", "COMBO", "COLOR",
                "COMFY_DYNAMICCOMBO_V3"}


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


def widget_names(info):
    """Ordered widget-input names for a node class (seed extra filtered by caller)."""
    names = []
    spec = info.get("input") or {}
    for group in ("required", "optional"):
        for name, entry in (spec.get(group) or {}).items():
            typ = entry[0]
            opts = entry[1] if len(entry) > 1 and isinstance(entry[1], dict) else {}
            if opts.get("forceInput"):
                continue
            if isinstance(typ, list) or typ in WIDGET_TYPES:
                names.append(name)
    return names


def convert(template_path, image_name):
    wf = json.loads(Path(template_path).read_text())
    nodes = {str(n["id"]): n for n in wf["nodes"]}
    links = {l[0]: l for l in wf.get("links", [])}

    info = api("GET", "/object_info")

    # collapse ComfySwitchNode widgets: boolean True -> input slot 1
    sw = {nid: n for nid, n in nodes.items() if n["type"] == "ComfySwitchNode"}
    for nid, n in sw.items():
        bools = (n.get("widgets_values") or [False])
        pick = bools[0] if isinstance(bools, list) and bools else bools
        n["_pick"] = TRELLIS_SWITCHES.get(nid, 1 if pick else 0)

    def resolve(link_id):
        """Follow a link, hopping through ComfySwitchNode selection."""
        l = links[link_id]
        src = str(l[1])
        if src in sw:
            node = nodes[src]
            want = node["_pick"]
            for inp in node.get("inputs") or []:
                if inp.get("link") is not None and int(inp.get("slot_index", inp.get("slot", 0))) == want:
                    return resolve(inp["link"])
            # fall back to ordering in the inputs array
            ins = [i for i in node.get("inputs") or [] if i.get("link") is not None]
            if len(ins) > want:
                return resolve(ins[want]["link"])
        return [src, l[2]]

    prompt = {}
    for nid, n in nodes.items():
        cls = n["type"]
        if cls in ("Note", "MarkdownNote", "ComfySwitchNode", "PrimitiveBoolean",
                   "PrimitiveInt", "CFGOverride") or cls not in info:
            # CFGOverride/Primitive* are real nodes but handled with widgets below
            if cls not in info:
                continue
        spec = info[cls]
        wnames = widget_names(spec)
        wvals = list(n.get("widgets_values") or [])
        if isinstance(n.get("widgets_values"), dict):  # some nodes store dicts
            wvals = [n["widgets_values"].get(k) for k in wnames]

        spec_in = {}
        for group in ("required", "optional"):
            spec_in.update((spec.get("input") or {}).get(group) or {})

        inputs = {}
        queue = list(wnames)
        wi = 0
        while queue and wi < len(wvals):
            name = queue.pop(0)
            inputs[name] = wvals[wi]
            wi += 1
            if name in ("seed", "noise_seed") and wi < len(wvals) and wvals[wi] in SEED_VALUES:
                wi += 1
            entry = spec_in.get(name) or [None]
            if entry[0] == "COMFY_DYNAMICCOMBO_V3":
                opts = (entry[1] or {}).get("options") or []
                chosen = next((o for o in opts if o.get("key") == inputs[name]), None)
                if chosen:
                    subs = ((chosen.get("inputs") or {}).get("required") or {})
                    queue = list(subs.keys()) + queue

        for inp in n.get("inputs") or []:
            if inp.get("link") is None:
                continue
            src = resolve(inp["link"])
            inputs[inp["name"]] = src

        prompt[nid] = {"class_type": cls, "inputs": inputs}

    # prune to what the output node actually needs
    keep, stack = set(), [MESH_OUT]
    while stack:
        nid = stack.pop()
        if nid in keep or nid not in prompt:
            continue
        keep.add(nid)
        for v in prompt[nid]["inputs"].values():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str):
                stack.append(v[0])
    prompt = {k: v for k, v in prompt.items() if k in keep}
    assert MESH_OUT in prompt, "pruned away the mesh we need"

    for nid, n in prompt.items():
        if n["class_type"] == "LoadImage":
            n["inputs"]["image"] = image_name

    # Save3DAdvanced wants a LOAD_3D viewport blob we cannot synthesise; the
    # smoothed mesh writes itself to GLB just as well.
    prompt = {k: v for k, v in prompt.items()
              if v["class_type"] not in ("Save3DAdvanced", "MeshToFile3D")}
    # RemeshMesh is a dynamic-combo node the API prompt cannot satisfy cleanly
    # (its sign_mode sub-inputs never validate). It only improves topology, so
    # feed the decoded shape mesh straight to Decimate.
    if "241" in prompt:
        src = prompt["241"]["inputs"]["mesh"]
        del prompt["241"]
        for n in prompt.values():
            for k, v in list(n["inputs"].items()):
                if isinstance(v, list) and len(v) == 2 and v[0] == "241":
                    n["inputs"][k] = src

    for n in prompt.values():
        if n["class_type"] == "DecimateMesh":
            n["inputs"]["target_face_count"] = DECIMATE_FACES
        if n["class_type"] == "PrimitiveInt":
            n["inputs"]["value"] = ATLAS

    prompt[OUTPUT_NODE] = {"class_type": "SaveGLB",
                           "inputs": {"mesh": ["260", 0], "filename_prefix": "3d/official"}}

    return prompt


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit("usage: trellis2_official.py <image.png> [out.glb]")
    src = Path(args[0])
    out = Path(args[1]) if len(args) > 1 else (VR / "pig_official.glb")
    if not src.is_file():
        sys.exit(f"missing image: {src}")

    INPUT.mkdir(parents=True, exist_ok=True)
    name = f"trellis_{src.stem}.png"
    shutil.copy(src, INPUT / name)

    prompt = convert(TEMPLATE, name)
    t0 = time.time()
    sub = api("POST", "/prompt", {"prompt": prompt, "client_id": uuid.uuid4().hex})
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
        print(json.dumps(status, indent=2)[:3000])
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
    print(f"done in {time.time() - t0:.1f}s -> {out} ({out.stat().st_size / 2**20:.1f} MB)")


if __name__ == "__main__":
    main()
