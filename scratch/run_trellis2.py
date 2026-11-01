"""Run the official TRELLIS.2 image-to-model template as-shipped.

Why this instead of hand-rolled projection texturing: projection can only paint
surfaces the single reference photo actually saw. TRELLIS.2 predicts the texture
in 3D, so the far flank, belly and inner legs get real content instead of sampled
white background. The template also bakes AO + normal maps and unwraps properly.

The previous TRELLIS attempt failed because the template was stripped down (the
RescaleCFG / CFGOverride nodes were dropped). So this script does NOT rebuild the
graph — it loads the shipped template, flips its Trellis.2 switch, points LoadImage
at our reference, and submits. The CFG nodes stay exactly where the authors put them.

ComfyUI's HTTP API needs "API format" (nodes keyed by id, inputs by name); the
template on disk is UI format (widgets_values arrays + a links table). The
converter below bridges the two.
"""
import json
import shutil
import sys
import time
import urllib.request
from pathlib import Path

COMFY = Path("/Users/dcruse/media-stack/ComfyUI")
TEMPLATE = (COMFY / ".venv/lib/python3.12/site-packages/"
            "comfyui_workflow_templates_json/templates/"
            "3d_pixal3d_trellis2_image_to_model.json")
HOST = "http://127.0.0.1:8188"
REF = Path("/Users/dcruse/media-stack/scratch/hog_cutout_tight.png")
REF_NAME = "hog_ref_tight.png"

# Allow a different reference/settings per asset instead of editing this file.
for _flag, _attr in (("--image", "REF"), ("--refname", "REF_NAME")):
    if _flag in sys.argv:
        _i = sys.argv.index(_flag)
        globals()[_attr] = Path(sys.argv[_i + 1]) if _attr == "REF" else sys.argv[_i + 1]
        del sys.argv[_i:_i + 2]
REF = Path(REF)
OUT_PREFIX = "3d/ComfyUI"
if "--prefix" in sys.argv:
    _i = sys.argv.index("--prefix")
    OUT_PREFIX = sys.argv[_i + 1]
    del sys.argv[_i:_i + 2]
TEXRES = 4096
if "--texres" in sys.argv:
    _i = sys.argv.index("--texres")
    TEXRES = int(sys.argv[_i + 1])
    del sys.argv[_i:_i + 2]

# Widgets that exist only in the UI and have no API input counterpart.
UI_ONLY = {"control_after_generate", "image_upload", "videopreview"}


def api(path, payload=None, timeout=60):
    url = f"{HOST}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    return json.loads(raw) if raw else {}


def load_object_info():
    return api("/object_info")


def widget_names(node_type, oi):
    """Ordered names of the widget-backed inputs for a node type."""
    spec = oi.get(node_type, {}).get("input", {})
    ordered = []
    for group in ("required", "optional"):
        for name, meta in spec.get(group, {}).items():
            kind = meta[0]
            # COMBO is a widget; a bare type string means a socket.
            if isinstance(kind, list) or kind in ("INT", "FLOAT", "STRING", "BOOLEAN",
                                                  "COMBO", "COLOR"):
                ordered.append(name)
            # Some defs append a control_after_generate pseudo-widget marker.
            if len(meta) > 1 and isinstance(meta[1], dict) and meta[1].get("control_after_generate"):
                ordered.append("control_after_generate")
    return ordered


def convert(ui, oi):
    """UI-format workflow -> API-format prompt dict."""
    nodes = {n["id"]: n for n in ui["nodes"]}
    # links: [link_id, origin_node, origin_slot, target_node, target_slot, type]
    links = {}
    for link in ui.get("links", []):
        lid, onode, oslot, tnode, tslot, _typ = link[:6]
        links[lid] = (str(onode), oslot)

    prompt = {}
    for nid, node in nodes.items():
        ntype = node.get("type")
        # mode 2 = muted, mode 4 = bypassed in ComfyUI
        if node.get("mode", 0) in (2, 4):
            continue
        if ntype in ("Note", "MarkdownNote"):
            continue

        inputs = {}
        # 1. widget values, in declaration order
        wv = node.get("widgets_values")
        if isinstance(wv, dict):
            inputs.update({k: v for k, v in wv.items() if k not in UI_ONLY})
        elif isinstance(wv, list):
            names = widget_names(ntype, oi)
            vi = 0
            for name in names:
                if vi >= len(wv):
                    break
                if name in UI_ONLY:
                    vi += 1
                    continue
                inputs[name] = wv[vi]
                vi += 1

        # 2. socket inputs, resolved from the links table
        for sock in node.get("inputs", []):
            lid = sock.get("link")
            if lid is None or lid not in links:
                continue
            src_id, src_slot = links[lid]
            inputs[sock["name"]] = [src_id, src_slot]

        prompt[str(nid)] = {"class_type": ntype, "inputs": inputs,
                            "_meta": {"title": node.get("title") or ntype}}
    return prompt


def find_node_by_type(ui, ntype):
    return [n for n in ui["nodes"] if n.get("type") == ntype]


def repair(prompt):
    """Fix inputs the UI fills in dynamically but the API rejects.

    The template stores Save3DAdvanced width as '' because the web UI substitutes
    the viewer size at queue time; over HTTP `int('')` fails and the node is
    dropped. More decisively, Save3DAdvanced/Preview3DAdvanced both require a
    `viewport_state` that has no API equivalent. We therefore drop the viewer nodes
    entirely and let MeshToFile3D (which needs only `mesh`) write the GLB.

    The Pixal3D-only branch is removed too: its UNET (`pixal3d_*`) and the MoGe
    camera model are not installed, and with the master switch set to TRELLIS.2
    they are unreachable anyway. ComfySwitchNode treats on_true/on_false as
    optional, so deleting the dead branch is safe.
    """
    DROP_IDS = {"319", "55", "56", "242", "298", "322", "246", "323"}
    DROP_CLASSES = {"Preview3DAdvanced", "Save3DAdvanced"}
    # Nodes whose widget layout includes a dynamic combo; positional mapping would
    # shift (e.g. RemeshMesh's sign_mode expands into extra widgets), so let the
    # node use its own defaults.
    DEFAULTS_ONLY = {"RemeshMesh"}

    for nid in list(prompt):
        if nid in DROP_IDS or prompt[nid]["class_type"] in DROP_CLASSES:
            print(f"[repair] dropped {nid} {prompt[nid]['class_type']}")
            del prompt[nid]

    for nid, node in prompt.items():
        if node["class_type"] in DEFAULTS_ONLY:
            node["inputs"] = {k: v for k, v in node["inputs"].items()
                              if isinstance(v, list)}

    # RemeshMesh: `sign_mode` is a COMFY_DYNAMICCOMBO_V3 that expands into hidden
    # sub-widgets, so the template's positional values [768,'solid',20,False,...]
    # shift by two. Writing them positionally put 20 into `band` (max 1.0). Set the
    # base inputs explicitly instead, matching the template's intent.
    for nid, node in prompt.items():
        if node["class_type"] != "RemeshMesh":
            continue
        node["inputs"].update({
            "resolution": 768,
            "sign_mode": "solid",
            "band": 1.0,
            "project_back": 0.0,
            "fix_poles": False,
            "smooth_iters": 20,
            "drop_small_components": 0.01,
            "precluster_max_verts": 20000000,
        })
        print(f"[repair] {nid} RemeshMesh set explicitly (dynamic combo)")

    # Nothing may point at a node we just removed. Every removed link was a
    # switch branch or a viewer input, all of them optional sockets.
    for nid, node in prompt.items():
        for key, val in list(node["inputs"].items()):
            if isinstance(val, list) and len(val) == 2 and str(val[0]) not in prompt:
                print(f"[repair] unlinked {nid}.{key} -> dropped {val[0]}")
                del node["inputs"][key]
    return prompt


def main():
    oi = load_object_info()

    # The reference must live in ComfyUI's input dir for LoadImage to find it.
    dest = COMFY / "input" / REF_NAME
    shutil.copy(REF, dest)
    print(f"[prep] staged reference -> {dest}")

    ui = json.loads(TEMPLATE.read_text())

    # Flip the single master boolean that selects TRELLIS.2 over Pixal3D.
    sw = find_node_by_type(ui, "PrimitiveBoolean")
    for n in sw:
        n["widgets_values"] = [True]
        print(f"[prep] switch node {n['id']} -> True (TRELLIS.2)")

    # Point the image loader at our hog.
    for n in find_node_by_type(ui, "LoadImage"):
        n["widgets_values"] = [REF_NAME, "image"]
        print(f"[prep] LoadImage node {n['id']} -> {REF_NAME}")

    # Cap the texture bake resolution at 4096 via the template's PrimitiveInt.
    for n in find_node_by_type(ui, "PrimitiveInt"):
        n["widgets_values"] = [4096, "fixed"]
        print(f"[prep] PrimitiveInt node {n['id']} -> 4096")

    prompt = convert(ui, oi)
    prompt = repair(prompt)
    print(f"[convert] {len(prompt)} nodes -> API format")

    # Report which save node we expect to write, so we know where to look.
    for nid, n in prompt.items():
        if n["class_type"] in ("Save3DAdvanced", "MeshToFile3D"):
            print(f"[output] node {nid} {n['class_type']} inputs={list(n['inputs'])}")

    out = Path("/Users/dcruse/media-stack/scratch/trellis2_prompt.json")
    out.write_text(json.dumps(prompt, indent=1))
    print(f"[convert] wrote {out}")

    r = api("/prompt", {"prompt": prompt})
    pid = r.get("prompt_id")
    print(f"[submit] prompt_id={pid}")
    if not pid:
        print("[submit] REJECTED:", json.dumps(r)[:2000])
        sys.exit(1)

    print(pid)


if __name__ == "__main__":
    main()
