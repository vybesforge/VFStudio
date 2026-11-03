"""auto_joints — let the local vision model place rig joints on a GLB.

  tools/.venv/bin/python tools/rig/auto_joints.py <src.glb> [--template biped|quadruped|auto]
      [--asset SLUG] [--out DIR] [--views DIR] [--vlm http://127.0.0.1:8082]
      [--model NAME] [--offline] [--keep-views]

Pipeline
 1. `render_views.py` (Blender, workbench) renders orthographic views + a manifest that
    maps blender world XYZ <-> pixel coordinates exactly.
 2. The views go to the local VLM (mlx_vlm server, :8082). One call classifies the asset
    and picks the view that shows the limbs spread out; one call asks for each landmark
    as a percentage of that image.
 3. Each landmark's two visible axes come from the model's answer, the third (depth)
    from the mesh itself: vertices inside a thin slab around the point, clustered along
    the depth axis so a left joint lands on the left limb, then medianed -> a point
    inside the limb rather than on its skin.
 4. Writes `rig/joints_<slug>.json` in glTF-space (Y up, what the browser picker uses)
    with `_template` and `_source`, so the room loads it for review and nudging.

Nothing leaves the machine: MLX VLM on 127.0.0.1, Blender local, trimesh local.
Coordinates are a *seed* — Qwen3-VL-8B is good for +-2-4% of body height, so the point
of this is to skip 17 manual clicks, not to skip the review.
"""
import argparse
import base64
import json
import math
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

STACK = Path(__file__).resolve().parents[2]
PY = STACK / "tools" / ".venv" / "bin" / "python"
BLENDER = STACK / "bin" / "blender"
RIG = STACK / "rig"
VLM_DEFAULT = os.environ.get("VLM_HOST", "http://127.0.0.1:8082")
VLM_MODEL = os.environ.get("VLM_MODEL", "mlx-community/Qwen3-VL-8B-Instruct-4bit")

# Landmarks must match vr/index.html TEMPLATES (name -> what to point at).
TEMPLATES = {
    "biped": [
        ("hips", "pelvis centre, where the legs fork from the torso", "wide"),
        ("spine", "lower back / navel height, centre of the torso", "wide"),
        ("chest", "sternum, centre of the ribcage", "wide"),
        ("neck", "base of the neck, between the collarbones", "wide"),
        ("head", "centre of the skull, roughly ear height", "wide"),
        ("L_shoulder", "the subject's LEFT shoulder joint (top of the upper arm)", "left"),
        ("L_elbow", "the subject's LEFT elbow", "left"),
        ("L_wrist", "the subject's LEFT wrist, where the hand starts", "left"),
        ("R_shoulder", "the subject's RIGHT shoulder joint (top of the upper arm)", "right"),
        ("R_elbow", "the subject's RIGHT elbow", "right"),
        ("R_wrist", "the subject's RIGHT wrist, where the hand starts", "right"),
        ("L_hip", "the subject's LEFT hip joint (top of the thigh)", "left"),
        ("L_knee", "the subject's LEFT knee", "left"),
        ("L_ankle", "the subject's LEFT ankle, just above the foot", "left"),
        ("R_hip", "the subject's RIGHT hip joint (top of the thigh)", "right"),
        ("R_knee", "the subject's RIGHT knee", "right"),
        ("R_ankle", "the subject's RIGHT ankle, just above the foot", "right"),
    ],
    "quadruped": [
        ("neck", "base of the head, where the neck meets the shoulders", "wide"),
        ("head", "tip of the snout", "wide"),
        ("spine", "middle of the back", "wide"),
        ("hips", "rear centre, above the hind legs", "wide"),
        ("FL_hip", "front shoulder, top of the front leg nearest the head", "left"),
        ("FL_knee", "front knee / carpal joint of that same front leg", "left"),
        ("FL_hoof", "front hoof of that same leg, on the ground", "left"),
        ("FR_hip", "front shoulder of the other front leg", "right"),
        ("FR_knee", "front knee of that other front leg", "right"),
        ("FR_hoof", "front hoof of that other front leg", "right"),
        ("BL_hip", "rear hip, top of the hind leg nearest the tail", "left"),
        ("BL_knee", "hind knee of that same hind leg", "left"),
        ("BL_hoof", "hind hoof of that same hind leg, on the ground", "left"),
        ("BR_hip", "rear hip of the other hind leg", "right"),
        ("BR_knee", "hind knee of that other hind leg", "right"),
        ("BR_hoof", "hind hoof of that other hind leg", "right"),
    ],
}

VIEW_LABELS = {"px": 1, "nx": 2, "py": 3, "ny": 4}
TO_VLM = {"px": "+X side", "nx": "-X side", "py": "+Y side", "ny": "-Y side"}


# ── VLM ─────────────────────────────────────────────────────────────────
def _img_part(path):
    ext = path.rsplit(".", 1)[-1].lower()
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}.get(ext, "image/png")
    b64 = base64.b64encode(open(path, "rb").read()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def vlm_up(host):
    try:
        urllib.request.urlopen(host + "/v1/models", timeout=3)
        return True
    except Exception:
        return False


def ask(host, model, parts, max_tokens=900, temp=0.1):
    payload = {"model": model, "messages": [{"role": "user", "content": parts}],
               "max_tokens": max_tokens, "temperature": temp, "stream": False}
    req = urllib.request.Request(host + "/v1/chat/completions", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"].strip()


def first_json(text):
    """Pull the first JSON object out of a model reply (it likes code fences and prose)."""
    text = re.sub(r"^```[a-z]*|```$", "", text.strip(), flags=re.M).strip()
    start = text.find("{")
    while start >= 0:
        depth = 0
        for i, ch in enumerate(text[start:], start):
            depth += (ch == "{") - (ch == "}")
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except Exception:
                    break
        start = text.find("{", start + 1)
    raise ValueError(f"no JSON in reply: {text[:300]}")


# ── views ───────────────────────────────────────────────────────────────
def render_views(src, outdir, res=1024):
    outdir.mkdir(parents=True, exist_ok=True)
    man = outdir / "views.json"
    if man.exists() and man.stat().st_mtime > Path(src).stat().st_mtime:
        cached = json.loads(man.read_text())
        if cached.get("res") == res:          # a re-render at a new size is a new manifest
            return cached
    cmd = [str(BLENDER), "-b", "--python", str(STACK / "tools" / "rig" / "render_views.py"),
           "--", str(src), str(outdir), str(res)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if not man.exists():
        sys.exit(f"render failed ({r.returncode}):\n{r.stdout[-1500:]}\n{r.stderr[-1500:]}")
    for line in r.stdout.splitlines():
        if "[views]" in line:
            print("  " + line)
    return json.loads(man.read_text())


def silhouette_box(path, thresh=12):
    """Bounding box of the subject in a workbench render (background is black).

    The camera frames 1.12x the model, so the figure never fills the render. Sending the
    model a padded image makes it normalise to the *subject*, not the frame: its knees and
    ankles then read high because a percent of the subject is not a percent of the picture.
    Cropping to this box and mapping percents into it removes the ambiguity."""
    from PIL import Image
    a = np.asarray(Image.open(path).convert("L"))
    ys, xs = np.nonzero(a > thresh)
    if not len(xs):
        return (0, 0, a.shape[1], a.shape[0])
    return (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)


def square_crop(path, box, out):
    """Crop to the subject and pad to a square, returning (x0, y0, side).

    Two normalisations bite here and both are aspect-driven: the model reads a 688x392
    render as if it were square, so a side-on animal came back with every joint too low
    and the snout off the end. A square canvas makes a percent a percent on both axes."""
    from PIL import Image
    x0, y0, x1, y1 = box
    side = max(x1 - x0, y1 - y0)
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    sx0, sy0 = cx - side // 2, cy - side // 2
    canvas = Image.new("RGB", (side, side), (0, 0, 0))
    src = Image.open(path).convert("RGB")
    sx0c, sy0c = max(0, sx0), max(0, sy0)
    piece = src.crop((sx0c, sy0c, min(src.width, sx0 + side), min(src.height, sy0 + side)))
    canvas.paste(piece, (sx0c - sx0, sy0c - sy0))
    canvas.save(out)
    return sx0, sy0, side


def montage(viewdir, names, out, cols=2):
    """Label every view 1..N on one sheet — a strip of four is 3072 px wide and the model
    loses track of which panel is which; a 2x2 grid keeps each view large."""
    from PIL import Image, ImageDraw
    ims = [Image.open(viewdir / f"{n}.png").convert("RGB") for n in names]
    w, h = ims[0].size
    rows = (len(ims) + cols - 1) // cols
    sheet = Image.new("RGB", (w * cols, h * rows), (0, 0, 0))
    d = ImageDraw.Draw(sheet)
    for i, im in enumerate(ims):
        px, py = (i % cols) * w, (i // cols) * h
        sheet.paste(im, (px, py))
        d.rectangle([px + 8, py + 8, px + 110, py + 92], fill=(20, 20, 20))
        d.text((px + 34, py + 28), str(i + 1), fill=(255, 255, 255))
        d.line([px, py, px + w, py], fill=(120, 120, 120), width=2)
        d.line([px, py, px, py + h], fill=(120, 120, 120), width=2)
    sheet.save(out)
    return out


# ── geometry ────────────────────────────────────────────────────────────
def blender_vertices(src):
    """Mesh vertices in Blender space (Z up); trimesh reads glTF (Y up) as x, -z, y."""
    import trimesh
    m = trimesh.load(str(src), force="mesh")
    v = np.asarray(m.vertices, dtype=np.float64)
    return np.column_stack([v[:, 0], -v[:, 2], v[:, 1]]), m


def img_to_plane(view, px, py):
    """Invert the manifest's pixel map for the two axes the view can see.

    The 2x3 pixel map is rank 2 (the camera axis contributes nothing), so least squares
    returns the point in the plane through the world origin; the caller reads only the
    two axes that actually carry information. None if the answer lands outside the frame."""
    ua = np.array(view["u"]); va = np.array(view["v"]); o = np.array(view["origin"])
    p = np.array([px - view["u0"], py - view["v0"]])
    A = np.vstack([ua, va])
    sol, *_ = np.linalg.lstsq(A, p, rcond=None)
    if np.linalg.norm(A @ sol - p) > 1.0:
        return None
    return o + sol


def gltf(p):
    """blender (x, y, z) -> glTF (x, z, -y): the space the browser picker saves."""
    return {"x": round(float(p[0]), 4), "y": round(float(p[2]), 4), "z": round(float(-p[1]), 4)}


def solve_point(V, l_axis, u_axis, d_axis, l, u, tol, side="wide", left_sign=None):
    """Bring an image-space guess onto the mesh.

    A thin slab around the guessed (l, u) collects the surface vertices that belong to
    that landmark; the third axis is then measured from the mesh, not guessed:
      * side left/right -> cluster the slab across the lateral axis and keep the limb the
        guess points at (separates two legs standing close together);
      * side near/far   -> cluster across the depth axis (a side-on quadruped hides one
        leg behind the other); `left_sign` says which end of that axis is the subject's left.
    Returns (point[3] in blender space, vertex count) or (None, 0)."""
    for widen in (1.0, 1.6, 2.4, 4.0):
        t = tol * widen
        sel = (np.abs(V[:, l_axis] - l) < t) & (np.abs(V[:, u_axis] - u) < t)
        idx = np.nonzero(sel)[0]
        if len(idx) >= 120:
            break
    if len(idx) < 12:
        return None, 0

    def two_means(a):
        c1, c2 = np.percentile(a, 25), np.percentile(a, 75)
        for _ in range(8):
            g1, g2 = a[abs(a - c1) <= abs(a - c2)], a[abs(a - c1) > abs(a - c2)]
            if not len(g1) or not len(g2):
                break
            c1, c2 = g1.mean(), g2.mean()
        return (c1, g1), (c2, g2)

    axis = l_axis if side in ("left", "right") else d_axis
    pick_idx = idx
    if side in ("left", "right") or left_sign is not None:
        (c1, g1), (c2, g2) = two_means(V[idx, axis])
        if abs(c2 - c1) > 2.0 * t:
            if side in ("left", "right"):
                keep = g1 if abs(c1 - l) <= abs(c2 - l) else g2
                pick_idx = idx[np.isin(V[idx, axis], keep)]
            else:                                    # quadruped near/far leg
                plus = g2 if c2 > c1 else g1         # vertices on the + end of the axis
                minus = g1 if plus is g2 else g2
                want_plus = (side == "left") == bool(left_sign)
                pick_idx = idx[np.isin(V[idx, axis], plus if want_plus else minus)]

    if len(pick_idx) < 6:
        pick_idx = idx
    p = np.array([np.median(V[pick_idx, 0]), np.median(V[pick_idx, 1]), np.median(V[pick_idx, 2])])
    p[l_axis], p[u_axis] = l, u                      # keep the model's in-plane answer
    p[d_axis] = np.median(V[pick_idx, d_axis])
    return p, len(pick_idx)


GRID = 20            # cells per axis: 5% of the crop per cell, ~2.5% after centring
_LETTERS = "ABCDEFGHIJKLMNOPQRST"


def grid_image(src, out, cols=GRID, rows=GRID):
    """Draw a labelled grid over the (square) crop and return it.

    Cell references replace coordinate regression on purpose: Qwen3-VL-8B answers the same
    question in percent, in a 0-1000 grid, or in pixels depending on the day, sometimes
    mixing two of those inside one reply. A cell name is unambiguous, and the grid lines
    give it something to measure against."""
    from PIL import Image, ImageDraw
    im = Image.open(src).convert("RGB")
    w, h = im.size
    d = ImageDraw.Draw(im)
    for c in range(cols + 1):
        x = c * w / cols
        d.line([x, 0, x, h], fill=(60, 120, 160), width=1)
    for r in range(rows + 1):
        y = r * h / rows
        d.line([0, y, w, y], fill=(60, 120, 160), width=1)
    for c in range(cols):
        lab = "ABCDEFGHIJKLMNOPQRST"[c % 20]
        d.text((c * w / cols + 3, 2), lab, fill=(255, 210, 0))
        d.text((c * w / cols + 3, h - 13), lab, fill=(255, 210, 0))
    for r in range(rows):
        d.text((2, r * h / rows + 1), str(r + 1), fill=(255, 210, 0))
        d.text((w - 16, r * h / rows + 1), str(r + 1), fill=(255, 210, 0))
    im.save(out)
    return out


CELL_RE = re.compile(r"^\s*([A-Ta-t])\s*[-]?\s*(\d{1,2})\s*$")


def cell_to_pct(val, cols=GRID, rows=GRID):
    """'C5' / [2,4] -> the centre of that cell as (x%, y%) of the square, or None."""
    if isinstance(val, (list, tuple)) and len(val) >= 2:
        try:
            c, r = int(val[0]), int(val[1])
        except Exception:
            return None
    elif isinstance(val, str):
        m = CELL_RE.match(val)
        if not m:
            return None
        c, r = "ABCDEFGHIJKLMNOPQRST".index(m.group(1).upper()), int(m.group(2)) - 1
    else:
        return None
    if not (0 <= c < cols and 0 <= r < rows):
        return None
    return (c + 0.5) * 100.0 / cols, (r + 0.5) * 100.0 / rows


def prompt(sq, template, listing):
    sides = ("The subject is seen FACE-ON, so its own left is on the RIGHT of the image."
             if template == "biped" else
             "The subject is seen SIDE-ON; give where each limb is along its body and how far off the ground.")
    return (
        f"A {template} 3D model on a grid: columns A-{_LETTERS[GRID-1]} left to right, rows 1-{GRID} "
        f"top to bottom. {sides}\n"
        "For every landmark below give the CELL that contains the joint centre, as a letter+number "
        'like "C5" or "H12" — read the letters on the top edge and the numbers on the left edge.\n'
        f"{listing}\n"
        "Rules: pick the cell whose middle is closest to the joint. A point you cannot see (a "
        "far-side elbow) is still where that joint is in projection. Do not invent landmarks that "
        "are absent — omit them.\n"
        'Reply with ONLY this JSON shape: {"<name>":"C5", ...}')


def review_prompt(sq):
    return (
        f"The red labelled circles are my proposed rig joints. Columns are A-{_LETTERS[GRID-1]} left to "
        f"right, rows 1-{GRID} top to bottom.\n"
        "Check every label against the anatomy and give the cell that belongs to each joint you would "
        'move, like {"L_knee":"F6"}. Leave out joints that are already correct; reply {} if none.')


def overlay(viewdir, view, joints, out, src=None, offset=(0, 0)):
    from PIL import Image, ImageDraw
    im = Image.open(src or (viewdir / view["file"])).convert("RGB")
    d = ImageDraw.Draw(im)
    ua = np.array(view["u"]); va = np.array(view["v"]); o = np.array(view["origin"])
    for name, g in joints.items():
        if name.startswith("_"):
            continue
        p = np.array([g["x"], -g["z"], g["y"]]) - o
        px = float(ua @ p) + view["u0"] - offset[0]
        py = float(va @ p) + view["v0"] - offset[1]
        d.ellipse([px - 4, py - 4, px + 4, py + 4], outline=(255, 40, 40), width=2)
        d.text((px + 6, py - 5), name, fill=(255, 40, 40))
    im.save(out)
    return out


# ── offline fallback ────────────────────────────────────────────────────
def fallback_joints(man, template):
    mn = np.array(man["bbox"]["min"]); mx = np.array(man["bbox"]["max"])
    size = mx - mn
    def P(fx, fy, fz):
        return mn + np.array([fx * size[0], fy * size[1], fz * size[2]])
    if template == "biped":
        # crude but correctly named: proportions of an upright figure, limbs split by width
        spec = {"hips": (0.5, 0.5, 0.52), "spine": (0.5, 0.5, 0.60), "chest": (0.5, 0.5, 0.72),
                "neck": (0.5, 0.5, 0.84), "head": (0.5, 0.5, 0.93),
                "L_shoulder": (0.34, 0.5, 0.81), "L_elbow": (0.30, 0.5, 0.63), "L_wrist": (0.28, 0.5, 0.45),
                "R_shoulder": (0.66, 0.5, 0.81), "R_elbow": (0.70, 0.5, 0.63), "R_wrist": (0.72, 0.5, 0.45),
                "L_hip": (0.44, 0.5, 0.52), "L_knee": (0.44, 0.5, 0.28), "L_ankle": (0.44, 0.5, 0.03),
                "R_hip": (0.56, 0.5, 0.52), "R_knee": (0.56, 0.5, 0.28), "R_ankle": (0.56, 0.5, 0.03)}
    else:
        spec = {"neck": (0.15, 0.5, 0.75), "head": (0.02, 0.5, 0.80), "spine": (0.55, 0.5, 0.72),
                "hips": (0.85, 0.5, 0.66)}
        for tag, fx, side in (("FL", 0.20, 0.36), ("FR", 0.20, 0.64), ("BL", 0.80, 0.36), ("BR", 0.80, 0.64)):
            spec[f"{tag}_hip"] = (fx, side, 0.52)
            spec[f"{tag}_knee"] = (fx, side, 0.28)
            spec[f"{tag}_hoof"] = (fx, side, 0.02)
    return {n: gltf(P(*v)) for n, v in spec.items()}


# ── main ────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--asset", default=None)
    ap.add_argument("--template", default="auto", choices=["auto", "biped", "quadruped"])
    ap.add_argument("--out", default=str(RIG))
    ap.add_argument("--views", default=None)
    ap.add_argument("--vlm", default=VLM_DEFAULT)
    ap.add_argument("--model", default=VLM_MODEL)
    ap.add_argument("--offline", action="store_true", help="skip the VLM, use bbox proportions")
    ap.add_argument("--no-refine", action="store_true", help="skip the second (review) VLM pass")
    ap.add_argument("--json", action="store_true", help="print one JSON line (for the panel)")
    args = ap.parse_args()

    src = Path(args.src).expanduser()
    if not src.is_file():
        sys.exit(f"no such GLB: {src}")
    asset = args.asset or src.stem.replace("_rigged", "")
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", asset).strip("-").lower()[:60] or "asset"
    viewdir = Path(args.views or (STACK / "scratch" / "rig-views" / slug))
    plan = {"asset": slug, "src": str(src), "template": None, "source": None, "joints": 0, "ok": False}

    print(f"[auto] {src.name} -> asset '{slug}'")
    man = render_views(src, viewdir)
    names = [v["name"] for v in man["views"] if v["name"] in VIEW_LABELS]
    sheet = montage(viewdir, names, viewdir / "montage.png")

    template = args.template
    template_note = ""
    joints = None
    if not args.offline and vlm_up(args.vlm):
        try:
            print("[auto] VLM: classify + pick the view")
            parts = [{"type": "text", "text":
                      "These are orthographic renders of one 3D asset, numbered 1-4 left to right.\n"
                      "Answer with JSON only: {\"kind\":\"biped\"|\"quadruped\"|\"other\","
                      "\"front\":<number of the view where you see the FACE straight on>,"
                      "\"profile\":<number of the view where you see the whole body LENGTH side-on>}"},
                     _img_part(str(sheet))]
            pick = first_json(ask(args.vlm, args.model, parts, max_tokens=200))
            kind = pick.get("kind")
            if template == "auto":
                template = kind if kind in TEMPLATES else "biped"
            by_num = {VIEW_LABELS[n]: n for n in names}
            vname = "profile" if template == "quadruped" else "front"
            chosen = by_num.get(int(pick.get(vname) or 0)) or names[0]
            print(f"[auto] VLM says kind={kind} -> template {template}, using view {chosen}")

            view = next(v for v in man["views"] if v["name"] == chosen)
            marks = TEMPLATES[template]
            listing = "\n".join(f"- {n} = {d}" for n, d, _ in marks)
            sides = ("The subject is seen FACE-ON, so its own left is on the RIGHT of the image."
                     if template == "biped" else
                     "The subject is seen SIDE-ON; give where each limb is along its body and how far off the ground.")
            box = silhouette_box(viewdir / view["file"])
            sq_x0, sq_y0, sq = square_crop(viewdir / view["file"], box, viewdir / f"crop_{chosen}.png")
            print(f"[auto] VLM: landmarks on {chosen}.png ({len(marks)} joints, subject box {box} -> square {sq}px)")
            crop_path = viewdir / f"crop_{chosen}.png"

            def place(val, side):
                """Answer -> a point on the mesh. Cell names carry the meaning; a numeric
                answer still arrives often enough (and in oscillating units) that it is
                read three ways and the first reading that lands on the mesh wins."""
                pct = cell_to_pct(val)
                if pct is not None:
                    candidates = [pct]
                else:
                    candidates = []
                    if isinstance(val, (list, tuple)) and len(val) >= 2:
                        for mode in ("px", "%", "/1000"):
                            f = {"px": 100.0 / sq, "%": 1.0, "/1000": 0.1}[mode]
                            candidates.append((float(val[0]) * f, float(val[1]) * f))
                for xp, yp in candidates:
                    if not (0.0 <= xp <= 100.0 and 0.0 <= yp <= 100.0):
                        continue
                    px = sq_x0 + xp / 100.0 * sq
                    py = sq_y0 + yp / 100.0 * sq
                    pt = img_to_plane(view, px, py)
                    if pt is None:
                        continue
                    cand, npts = solve_point(V, known[0], known[1], cam_axis,
                                             float(pt[known[0]]), float(pt[known[1]]), tol,
                                             side=side, left_sign=left_sign)
                    if cand is not None:
                        return cand, npts, "cell" if pct is not None else "num"
                return None, 0, "?"

            grid = grid_image(crop_path, viewdir / f"grid_{chosen}.png")
            raw = ask(args.vlm, args.model, [_img_part(str(grid)),
                                             {"type": "text", "text": prompt(sq, template, listing)}],
                      max_tokens=1200)
            (viewdir / "vlm_reply.txt").write_text(raw)
            got = first_json(raw)

            V, mesh = blender_vertices(src)
            tol = 0.045 * float(man["span"])
            cam_axis = int(np.argmax(np.abs(view["axis"])))
            known = [i for i in range(3) if i != cam_axis]
            # A side-on quadruped hides one leg behind the other: find out which end of the
            # depth axis is the subject's own left, once, from a face-on view.
            left_sign = None
            if template == "quadruped":
                fv = next((v for v in man["views"] if VIEW_LABELS.get(v["name"]) == int(pick.get("front") or 0)), None)
                if fv is not None:
                    try:
                        r2 = first_json(ask(args.vlm, args.model, [
                            {"type": "text", "text": f"Image number {VIEW_LABELS[fv['name']]}: which side of the "
                                                     "IMAGE is the subject's own left? JSON only: "
                                                     '{"left":"image-left"} or {"left":"image-right"}'},
                            _img_part(str(viewdir / fv["file"]))], max_tokens=100))
                        axis_u = np.array(fv["u"])
                        a = int(np.argmax(np.abs(axis_u)))       # world axis shown left-to-right
                        sign_u = float(np.sign(axis_u[a]))       # +world axis is image-right
                        want_plus = (sign_u > 0) if r2.get("left") == "image-right" else (sign_u < 0)
                        if a == cam_axis:
                            left_sign = bool(want_plus)
                        print(f"[auto] subject-left is +world axis {a} = {want_plus} "
                              f"(profile depth axis {cam_axis} -> left_sign {left_sign})")
                    except Exception as exc:
                        print(f"[auto] left/right probe failed ({exc}) — left legs may come back swapped; "
                              "hit 'Mirror L→R' in the picker")

            out = {}
            for name, _desc, side in marks:
                xyp = got.get(name)
                if not isinstance(xyp, (str, list, tuple)):
                    continue
                p, npts, units = place(xyp, side)
                if p is None:
                    print(f"[auto]   {name}: nothing on the mesh for {xyp} — skipped")
                    continue
                if units != "px":
                    print(f"[auto]   {name}: read as {units} (n={npts})")
                out[name] = gltf(p)

            # One review round: the model is much better at judging a labelled picture than
            # at blind coordinate regression, so show it what it just placed and let it move
            # the ones that are wrong. Only the joints it names are touched.
            if out and not args.no_refine:
                ov = overlay(viewdir, view, out, viewdir / f"review_{chosen}.png",
                            src=grid, offset=(sq_x0, sq_y0))
                move = ask(args.vlm, args.model, [_img_part(str(ov)), {"type": "text", "text": review_prompt(sq)}],
                           max_tokens=900)
                (viewdir / "vlm_review.txt").write_text(move)
                try:
                    fixes = first_json(move)
                except Exception:
                    fixes = {}
                moved = 0
                for name, xyp in (fixes or {}).items():
                    if name not in out or not isinstance(xyp, (str, list, tuple)):
                        continue
                    side = next((s for n, _d, s in marks if n == name), "wide")
                    p, npts, units = place(xyp, side)
                    if p is not None:
                        out[name] = gltf(p)
                        moved += 1
                print(f"[auto] review moved {moved} joints — {ov}")

            if out:
                joints, plan["source"] = out, "vlm"
                ov = overlay(viewdir, view, out, viewdir / "overlay.png")
                print(f"[auto] {len(out)}/{len(marks)} joints placed — overlay {ov}")
        except Exception as exc:
            print(f"[auto] VLM path failed: {exc}")
            template_note = f" (VLM failed: {exc})"
    else:
        print("[auto] VLM not reachable on " + args.vlm)

    if not joints:
        if template == "auto":
            template = "biped"
        joints = fallback_joints(man, template)
        plan["source"] = "bbox-fallback"
        print(f"[auto] falling back to bbox proportions{template_note}")

    joints["_template"] = template
    joints["_source"] = plan["source"]
    joints["_src"] = src.name
    dest = Path(args.out) / f"joints_{slug}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(joints, indent=1))
    plan.update({"template": template, "joints": len([k for k in joints if not k.startswith("_")]),
                 "path": str(dest), "ok": True, "views": str(viewdir)})
    print(f"[auto] wrote {dest} ({plan['joints']} joints, template {template}, source {plan['source']})")
    if args.json:
        print(json.dumps(plan))
    return plan


if __name__ == "__main__":
    main()
