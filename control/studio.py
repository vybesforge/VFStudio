"""studio.py — the Studio page for the media-stack panel.

Adds to panel.py (one origin, :8787):
  tabs per modality (Image / Video / 3D & VR / Sound / Voice) with a run form, a live
  progress bar for the current ComfyUI job, and an inline preview gallery of outputs;
  plus Models (manifest inventory) and Tools (what is installed) views.

API:
  GET  /api/studio/inventory         manifest models present/missing, tools, services
  GET  /api/studio/outputs?kind=     recent output files for a modality, with preview URLs
  GET  /api/studio/progress          current ComfyUI job progress (from its websocket)
  POST /api/studio/run               {"kind": "image", "args": {...}}  -> job id
  GET  /api/studio/jobs              recent jobs (status, result, log tail)
  POST /api/studio/jobs/{id}/cancel

Jobs shell out to the same CLIs an agent uses (`gen`, `voice`, `vid`), so the page and
the skills never drift apart.
"""
from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

HOME = Path.home()
STACK = HOME / "media-stack"
OUT = STACK / "output"
THUMBS = OUT / ".thumbs"
COMFY_OUT = STACK / "ComfyUI" / "output"
# The second ComfyUI instance (:8190, stills lane) is started with
# --output-directory ~/comfy/output-b, so its renders never appear under
# ComfyUI/output. The gallery has to read both roots or work done in that
# instance's own UI looks lost.
COMFY_OUT_ALT = Path(os.path.expanduser("~/comfy/output-b"))
MODELS = STACK / "ComfyUI" / "models"
MANIFEST = STACK / "models" / "manifest.json"
JOBS_LOG = STACK / "logs" / "studio-jobs.jsonl"
GEN = STACK / "tools" / "comfy" / "gen"
LORA = STACK / "tools" / "train" / "lora"
DATASETS = STACK / "train" / "datasets"
LORAS_DIR = STACK / "ComfyUI" / "models" / "loras"
VOICE = STACK / "tools" / "voice" / "voice"
STEMS = STACK / "tools" / "audio" / "stems"
VID = STACK / "tools" / "video" / "vid"
WRITE = STACK / "tools" / "llm" / "scribe"   # not "write": macOS owns that name
SEE = STACK / "tools" / "vision" / "see"
TRELLIS3D = STACK / "tools" / "comfy" / "trellis3d"
FFMPEG = next((p for p in (HOME / ".hermes" / "tools").glob("ffmpeg-*/ffmpeg")), None)

router = APIRouter(prefix="/api/studio")

# ───────────────────────── inventory ─────────────────────────
TOOLS = [
    ("gen", GEN, "ComfyUI pipelines: image / control / upscale / video / sfx / music"),
    ("trellis3d", TRELLIS3D, "TRELLIS.2 image -> textured GLB (headless: SaveGLB on the shipped template)"),
    ("voice", VOICE, "TTS, voice clone, transcribe, enhance (mlx-audio)"),
    ("vid", VID, "ffmpeg wrapper: trim / concat / captions / gif / loudness"),
    ("scribe", WRITE, "uncensored creative writing over the local LLM (prose/outline/screenplay/dialogue/lore)"),
    ("see", SEE, "local vision: describe / ask / ocr / compare, camera snap"),
    ("imagesnap", Path("/opt/homebrew/bin/imagesnap"), "camera capture"),
    ("vse_build.py", STACK / "tools" / "video" / "vse_build.py", "Blender VSE timeline assembler"),
    ("slice", STACK / "tools" / "print" / "slice", "OrcaSlicer CLI: STL → G-code / 3MF (bambu | generic)"),
    ("meshcheck.py", STACK / "tools" / "print" / "meshcheck.py", "watertight / volume / repair check for STL"),
    ("optimize_glb.sh", STACK / "tools" / "vr" / "optimize_glb.sh", "gltf-transform: decimate + resize textures for VR"),
    ("blender", STACK / "bin" / "blender", "Blender 5.2 headless wrapper"),
    ("fetch-models", STACK / "bin" / "fetch-models", "download missing manifest models"),
    ("Godot", Path("/Applications/Godot.app"), "Godot 4.7 OpenXR room (~/media-stack/vr-godot)"),
    ("OrcaSlicer", Path("/Applications/OrcaSlicer.app"), "slicer GUI + CLI"),
    ("Krita", Path("/Applications/Krita.app"), "raster painting"),
    ("Inkscape", Path("/Applications/Inkscape.app"), "vector editing / SVG for laser & print"),
    ("Audacity", Path("/Applications/Audacity 4.app"), "audio editing"),
    ("OpenSCAD", Path("/Applications/OpenSCAD.app"), "code-CAD (.scad)"),
    ("MeshLab", Path("/Applications/MeshLab2025.07.app"), "mesh inspection / repair"),
    ("ffmpeg", FFMPEG or Path("/nonexistent"), "bundled ffmpeg 9"),
]

GROUPS = [
    ("Image", ["flux1-dev-fp8", "z-image-turbo", "z-image-te", "z-image-vae", "z-image-controlnet-union",
               "flux2-klein-4b", "flux2-vae", "qwen-image-edit-2509", "qwen-image-edit-2509-gguf", "qwen-2.5-vl-7b", "qwen-image-vae",
               "animagine-xl-4.0",
               "4x-ultrasharp", "realesrgan-x4plus", "seedvr2-3b-int8", "seedvr2-vae"]),
    ("Video", ["wan2.2-ti2v-5b", "wan2.2-vae", "umt5-xxl-fp8"]),
    ("3D", ["trellis2-int8", "trellis2-shape-vae", "trellis2-texture-vae", "dinov3-L", "birefnet"]),
    ("Sound", ["stable-audio-open-1.0", "t5-base", "stable-audio-3-medium", "t5gemma-b-b-ul2", "ace-step-1.5-turbo-aio"]),
]

AUDIO_MODELS = [
    ("mlx-community/Kokoro-82M-bf16", "TTS (50+ voices)"),
    ("mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16", "voice cloning"),
    ("mlx-community/chatterbox-turbo-fp16", "voice cloning (fallback)"),
    ("mlx-community/whisper-large-v3-turbo-asr-fp16", "speech-to-text"),
    ("mlx-community/MiniMax-Music3-8bit", "music (mlx, `stack music`)"),
    ("mlx-community/Qwen3.8-27B-Uncensored-OptiQ-4bit", "writer LLM (uncensored, :8081)"),
    ("mlx-community/Qwen3-VL-8B-Instruct-4bit", "vision VLM (:8082)"),
]


def _hf_cached(repo: str) -> bool:
    d = HOME / ".cache" / "huggingface" / "hub" / ("models--" + repo.replace("/", "--"))
    return d.exists() and any(d.glob("snapshots/*/*"))


@router.get("/inventory")
def inventory():
    man = json.load(open(MANIFEST))["models"] if MANIFEST.exists() else []
    by_id = {m["id"]: m for m in man}
    groups = []
    for label, ids in GROUPS:
        rows = []
        for i in ids:
            m = by_id.get(i)
            if not m:
                continue
            p = MODELS / m["path"]
            part = Path(str(p) + ".part")
            rows.append({"id": i, "role": m["role"], "gb": m["gb"], "path": m["path"],
                         "present": p.exists(), "downloading": part.exists(),
                         "part_gb": round(part.stat().st_size / 1e9, 2) if part.exists() else 0})
        groups.append({"label": label, "models": rows})
    known = {i for _, ids in GROUPS for i in ids}
    extra = [{"id": m["id"], "role": m["role"], "gb": m["gb"], "path": m["path"],
              "present": (MODELS / m["path"]).exists(), "downloading": False, "part_gb": 0}
             for m in man if m["id"] not in known]
    if extra:
        groups.append({"label": "Other", "models": extra})
    audio = [{"id": r, "role": n, "present": _hf_cached(r)} for r, n in AUDIO_MODELS]
    tools = [{"name": n, "path": str(p), "present": p.exists(), "desc": d} for n, p, d in TOOLS]
    present_gb = sum(m["gb"] for g in groups for m in g["models"] if m["present"])
    total_gb = sum(m["gb"] for g in groups for m in g["models"])
    return {"groups": groups, "audio": audio, "tools": tools,
            "present_gb": round(present_gb, 1), "total_gb": round(total_gb, 1)}


# ───────────────────────── outputs ─────────────────────────
EXT = {
    "image": {".png", ".jpg", ".jpeg", ".webp"},
    "video": {".mp4", ".webm", ".mov", ".gif"},
    "sound": {".wav", ".flac", ".mp3", ".ogg", ".opus"},
    "voice": {".wav", ".flac", ".mp3"},
    "3d": {".glb", ".gltf", ".obj", ".stl"},
    "text": {".md", ".txt", ".json", ".fountain", ".srt"},
    "camera": {".jpg", ".jpeg", ".png"},
}
# where each modality's files live; (dir, url mount)
ROOTS = {
    "image": [(OUT / "image", "/files/output/image"), (OUT / "control", "/files/output/control"),
              (OUT / "upscale", "/files/output/upscale"), (COMFY_OUT, "/files/comfy_output"),
              (COMFY_OUT_ALT, "/files/comfy_output_b")],
    "video": [(OUT / "video", "/files/output/video"), (OUT / "image" / "uploads", "/files/output/image/uploads"), (COMFY_OUT / "video", "/files/comfy_output/video"),
              (COMFY_OUT_ALT / "video", "/files/comfy_output_b/video"),
              (STACK / "scratch" / "video-test", "/files/scratch/video-test")],
    "sound": [(OUT / "sfx", "/files/output/sfx"), (OUT / "music", "/files/output/music"), (OUT / "stems", "/files/output/stems"),
              (COMFY_OUT / "audio", "/files/comfy_output/audio"), (COMFY_OUT_ALT / "audio", "/files/comfy_output_b/audio"),
              (STACK / "scratch", "/files/scratch")],
    "voice": [(OUT / "voice", "/files/output/voice"), (STACK / "scratch" / "voice-test", "/files/scratch/voice-test")],
    "text": [(OUT / "text", "/files/output/text")],
    "camera": [(OUT / "camera", "/files/output/camera"), (OUT / "image", "/files/output/image")],
    "3d": [(STACK / "vr", "/vr"), (COMFY_OUT / "3d", "/files/comfy_output/3d"), (OUT / "3d", "/files/output/3d"),
           (STACK / "scratch" / "print-test", "/files/scratch/print-test"), (STACK / "scratch" / "vr-test", "/files/scratch/vr-test")],
}


GAME_DIR = STACK / "game"
GAME_SKIP = {"node_modules", ".godot", "dist", "build", ".git", "templates", "__pycache__", ".import"}


def _game_projects():
    """Every folder under ~/media-stack/game that is a Godot or web project (templates excluded)."""
    out = []
    if not GAME_DIR.is_dir():
        return out
    for d in sorted(GAME_DIR.iterdir()):
        if not d.is_dir() or d.name in GAME_SKIP or d.name == "tools":
            continue
        kind = "godot" if (d / "project.godot").exists() else "web" if (d / "package.json").exists() or (d / "index.html").exists() else None
        if not kind:
            continue
        counts = {}
        for p in d.rglob("*"):
            if any(part in GAME_SKIP for part in p.relative_to(d).parts[:-1]) or not p.is_file():
                continue
            for k, exts in EXT.items():
                if p.suffix.lower() in exts:
                    counts[k] = counts.get(k, 0) + 1
        play = None
        if kind == "web" and (d / "dist" / "index.html").exists():
            play = f"/files/game/{d.name}/dist/index.html"
        readme = next((p for p in d.glob("README*")), None)
        out.append({"name": d.name, "kind": kind, "path": str(d), "assets": counts, "play": play,
                    "readme": readme.read_text(errors="replace")[:600] if readme else "",
                    "mtime": d.stat().st_mtime, "when": time.strftime("%m-%d %H:%M", time.localtime(d.stat().st_mtime))})
    out.sort(key=lambda x: -x["mtime"])
    return out


# Anything an AI writes under these trees is visible in the galleries, whatever subfolder it invents.
# Extension filter per kind still applies, so a .glb in output/image/ shows under 3D, etc.
BROAD_ROOTS = [(OUT, "/files/output"), (STACK / "scratch", "/files/scratch"), (COMFY_OUT, "/files/comfy_output"),
               (COMFY_OUT_ALT, "/files/comfy_output_b"),
               (Path.home() / ".hermes" / "cache" / "generated" / "images", "/files/images")]


@router.get("/games")
def games():
    return {"projects": _game_projects()}



@router.get("/outputs")
def outputs(kind: str = "image", limit: int = 48, offset: int = 0):
    """Gallery listing. Paged — the old signature returned the first 48 and had no
    way to reach the rest, so a busy day looked like lost work.

    Returns `total` (everything that matched) alongside the requested slice, so the
    UI can say "showing 48 of 562" and offer a real next page.
    """
    if kind not in ROOTS:
        raise HTTPException(400, "unknown kind")
    limit = max(1, min(int(limit), 5000))
    offset = max(0, int(offset))
    exts = EXT[kind]
    seen, items = set(), []
    roots = list(ROOTS[kind]) + BROAD_ROOTS
    # game projects contribute their own assets (models, audio, sprites) to every gallery
    for g in _game_projects():
        roots.append((Path(g["path"]), f"/files/game/{g['name']}"))
    for d, mount in roots:
        if not d.is_dir():
            continue
        for p in d.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in exts or ".part" in p.name:
                continue
            if any(part in GAME_SKIP or part.startswith(".") or part == "uploads_tmp" for part in p.relative_to(d).parts[:-1]):
                continue
            rp = p.resolve()
            st = p.stat()
            # same file under two roots (gen copies ComfyUI/output/* into output/<kind>/): keep the first root's copy
            key = (p.name, st.st_size)
            if rp in seen or key in seen or (d.parent == GAME_DIR and p.name.lower().startswith("readme")):
                continue
            seen.add(rp); seen.add(key)
            rel = p.relative_to(d).as_posix()
            items.append({"name": p.name, "path": str(p), "url": f"{mount}/{rel}", "bytes": st.st_size,
                          "mtime": st.st_mtime, "when": time.strftime("%m-%d %H:%M", time.localtime(st.st_mtime)),
                          "ext": p.suffix.lower().lstrip(".")})
    items.sort(key=lambda x: -x["mtime"])
    total = len(items)
    page = items[offset:offset + limit]
    return {"kind": kind, "items": page, "total": total,
            "offset": offset, "limit": limit, "has_more": offset + len(page) < total}


# ───────────────────────── ComfyUI progress (websocket listener) ─────────────────────────
# ComfyUI sends execution_start / executing / progress only to the socket whose clientId
# submitted the prompt. `gen` and the Hermes image_gen plugin both submit as "gen-cli", so
# the panel connects under that id and receives their step-by-step progress.
_progress = {"connected": False, "prompt_id": None, "node": None, "value": 0, "max": 0,
             "status": "idle", "started": None, "updated": None, "queue_remaining": 0, "last_node_type": None}
_plock = threading.Lock()

# Per-instance, per-prompt progress, keyed by (backend_port, prompt_id).
# The single-dict tracker above could not survive the second V100: two ComfyUI
# instances overwrote each other's value/max, which is why the old header tile
# showed "step 8/20" with prompt_id=null and no idea whose job it was.
_PROG: dict = {}
_ws_up: dict = {}
_PROG_TTL = 900.0


def _default_comfy_ports():
    """ComfyUI backend ports to listen on, per platform.

    VF_COMFY_PORTS overrides (comma separated). macOS runs ComfyUI directly on
    8188; the Linux box runs a shim on 8188 that forwards to a backend on 8189,
    plus a second instance on 8190 for the second card.
    """
    env = os.environ.get("VF_COMFY_PORTS", "").strip()
    if env:
        ports = tuple(int(p) for p in env.split(",") if p.strip().isdigit())
        if ports:
            return ports
    return (8188,) if sys.platform == "darwin" else (8189, 8190)


COMFY_BACKEND_PORTS = _default_comfy_ports()


def _apply_progress(port: int, t: str, d: dict, now: float):
    """Fold one websocket message into _PROG, and mirror :8189 into legacy _progress."""
    pid = d.get("prompt_id")

    if t == "execution_start" and pid:
        _PROG[(port, pid)] = {"value": 0, "max": 0, "node": None,
                              "status": "running", "started": now, "updated": now}
    elif t == "executing":
        if d.get("node") is None:
            if pid and (port, pid) in _PROG:
                e = _PROG[(port, pid)]
                e.update(status="done", value=e.get("max") or 1, max=e.get("max") or 1, updated=now)
        elif pid and (port, pid) in _PROG:
            _PROG[(port, pid)]["node"] = d.get("node")
    elif t in ("progress", "progress_state") and pid:
        e = _PROG.setdefault((port, pid), {"value": 0, "max": 0, "node": None,
                                           "status": "running", "started": now, "updated": now})
        cur = e.get("node")
        if t == "progress":
            mx = d.get("max") or 0
            # Ignore degenerate counters (max=1 utility nodes); a real sampler has steps.
            if mx >= 2:
                e.update(value=d.get("value") or 0, max=mx, node=d.get("node"),
                         status="running", updated=now)
        else:
            # progress_state snapshots every node. Stay on the node we already track
            # while it is still running, otherwise the headline number jumps between
            # nodes and the bar jitters (saw 84% → 15% → 65% inside one job).
            nodes = d.get("nodes") or {}
            keep = nodes.get(str(cur)) if cur is not None else None
            if isinstance(keep, dict) and (keep.get("max") or 0) >= 2 \
               and keep.get("state") in (None, "running"):
                e.update(value=keep.get("value") or 0, max=keep.get("max") or 0,
                         status="running", updated=now)
            else:
                best = None
                for nid, nd in nodes.items():
                    if not isinstance(nd, dict):
                        continue
                    mx = nd.get("max") or 0
                    if mx < 2 or nd.get("state") not in (None, "running"):
                        continue
                    if best is None or mx > (best[1].get("max") or 0):
                        best = (nid, nd)
                if best:
                    nid, nd = best
                    e.update(value=nd.get("value") or 0, max=nd.get("max") or 0,
                             node=nid, status="running", updated=now)
    elif t in ("execution_error", "execution_interrupted") and pid:
        _PROG.setdefault((port, pid), {}).update(
            status="error" if t == "execution_error" else "interrupted", updated=now)

    # Legacy single tracker, fed from :8189 so /progress keeps working for old callers.
    if port == 8189:
        _progress["updated"] = now
        if t == "status":
            _progress["queue_remaining"] = (d.get("status") or {}).get("exec_info", {}).get("queue_remaining", 0)
            if _progress["queue_remaining"] == 0 and _progress["status"] != "running":
                _progress["status"] = "idle"
        elif t == "execution_start":
            _progress.update(prompt_id=pid, status="running", started=now, value=0, max=0, node=None)
        elif t == "executing":
            if d.get("node") is None:
                _progress.update(status="done", node=None,
                                 value=_progress["max"] or 1, max=_progress["max"] or 1)
            else:
                _progress["node"] = d.get("node")
        elif t == "progress":
            _progress.update(value=d.get("value", 0), max=d.get("max", 0),
                             node=d.get("node"), status="running")
        elif t == "execution_error":
            _progress.update(status="error", node=None)
        elif t == "execution_interrupted":
            _progress.update(status="interrupted", node=None)


def _ws_loop(port: int):
    try:
        import websocket  # websocket-client
    except Exception:
        return
    url = f"ws://127.0.0.1:{port}/ws?clientId=gen-cli"
    while True:
        try:
            ws = websocket.create_connection(url, timeout=5)
            ws.settimeout(30)
            with _plock:
                _ws_up[port] = True
                if port == 8189:
                    _progress["connected"] = True
            while True:
                try:
                    raw = ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                if not isinstance(raw, str):
                    continue
                msg = json.loads(raw)
                now = time.time()
                with _plock:
                    _apply_progress(port, msg.get("type"), msg.get("data") or {}, now)
                    for k, v in list(_PROG.items()):
                        if now - (v.get("updated") or 0) > _PROG_TTL:
                            _PROG.pop(k, None)
        except Exception:
            with _plock:
                _ws_up[port] = False
                if port == 8189:
                    _progress["connected"] = False
            time.sleep(3)


def progress_for(port: int, prompt_id):
    """Live {value,max,node,status} for one prompt on one instance, or None."""
    if not prompt_id:
        return None
    with _plock:
        entry = _PROG.get((port, prompt_id))
        return dict(entry) if entry else None


def ws_connected(port: int) -> bool:
    with _plock:
        return bool(_ws_up.get(port))


for _p in COMFY_BACKEND_PORTS:
    threading.Thread(target=_ws_loop, args=(_p,), daemon=True, name=f"comfy-ws-{_p}").start()


@router.get("/progress")
def progress():
    with _plock:
        p = dict(_progress)
    # Jobs submitted by other clients (ComfyUI's own UI, e.g. TRELLIS runs) only reach us
    # as queue counts: show them as running with an indeterminate bar.
    if p["status"] != "running":
        try:
            import urllib.request as u
            q = json.loads(u.urlopen("http://127.0.0.1:8188/queue", timeout=2).read())
            if q.get("queue_running"):
                p.update(status="running", value=0, max=0, node="(external client)", prompt_id=q["queue_running"][0][1])
                p["started"] = p["started"] if p.get("started") and p["status"] == "running" else None
        except Exception:
            pass
    p["elapsed"] = round(time.time() - p["started"], 1) if p.get("started") and p["status"] == "running" else None
    return p


# ───────────────────────── jobs ─────────────────────────
_jobs: dict[str, dict] = {}
_jlock = threading.Lock()


def _env() -> dict:
    env = os.environ.copy()
    if FFMPEG:
        env["PATH"] = f"{FFMPEG.parent}:{env['PATH']}"
    return env


def _build_cmd(kind: str, a: dict) -> list[str]:
    def flag(name, key=None, cast=str):
        v = a.get(key or name.lstrip("-").replace("-", "_"))
        return [name, str(cast(v))] if v not in (None, "", False) else []

    if kind == "image":
        cmd = [str(GEN), "image", a["prompt"], "--model", a.get("model", "zimage"),
               *flag("--w", cast=int), *flag("--h", cast=int), *flag("--steps", cast=int), *flag("--seed", cast=int), *flag("--n", cast=int)]
        # anime lane (animagine): real negative prompt + real CFG
        if a.get("model") == "animagine":
            cmd += [*flag("--negative"), *flag("--cfg", cast=float)]
        if a.get("lora"):
            cmd += ["--lora", f"{a['lora']}:{a.get('lora_strength') or 1.0}"]
        return cmd
    if kind == "mesh3d":
        # TRELLIS.2 image -> textured GLB, headless (SaveGLB appended to the shipped template)
        return [str(TRELLIS3D), a["image"], "--prefix", a.get("prefix") or "3d/mesh",
                *flag("--texres", cast=int)]
    if kind == "lora":
        return [str(LORA), "train", "--dataset", str(DATASETS / a["dataset"]), "--name", a["name"], "--model", a.get("model", "zimage"),
                *flag("--steps", cast=int), *flag("--rank", cast=int), *flag("--res", cast=int), *flag("--trigger"), *flag("--save-every", cast=int), "-v"]
    if kind == "control":
        return [str(GEN), "control", a["prompt"], "--image", a["image"], "--mode", a.get("mode", "canny"),
                *flag("--strength", cast=float), *flag("--steps", cast=int), *flag("--seed", cast=int), "--save-control"]
    if kind == "upscale":
        return [str(GEN), "upscale", a["image"], "--method", a.get("method", "esrgan"), *flag("--scale", cast=float)]
    if kind == "edit":
        cmd = [str(GEN), "edit", a["image"], a["prompt"], *flag("--ref2"), *flag("--ref3"), *flag("--seed", cast=int), *flag("--steps", cast=int)]
        if a.get("fast", True) not in (False, "false", "0", ""):
            cmd.append("--fast")
        return cmd
    if kind == "video":
        # --seconds drives length (frames = seconds x fps); gen splits anything over the
        # model's native 121 frames into chained passes and stitches them.
        return [str(GEN), "video", a["prompt"], "--model", a.get("model", "wan"), *flag("--image"), *flag("--w", cast=int), *flag("--h", cast=int),
                *flag("--seconds", cast=float), *flag("--frames", cast=int), *flag("--fps", cast=int),
                *flag("--steps", cast=int), *flag("--seed", cast=int)]
    if kind == "sfx":
        return [str(GEN), "sfx", a["prompt"], "--model", a.get("model", "sa3sfx"), *flag("--seconds", cast=float),
                *flag("--steps", cast=int), *flag("--seed", cast=int)]
    if kind == "music":
        cmd = [str(GEN), "music", a["prompt"], *flag("--seconds", cast=float), *flag("--bpm", cast=int),
               *flag("--key"), *flag("--seed", cast=int)]
        if a.get("lyrics"):
            cmd += ["--lyrics", a["lyrics"]]
        return cmd
    if kind == "stems":
        if a.get("karaoke"):
            return [str(STEMS), "karaoke", a["file"]]
        return [str(STEMS), "split", a["file"], "--model", a.get("model", "htdemucs")]
    if kind == "say":
        out = OUT / "voice" / f"say_{int(time.time())}.wav"
        return [str(VOICE), "say", a["text"], "--voice", a.get("voice", "af_heart"), "--out", str(out)]
    if kind == "clone":
        out = OUT / "voice" / f"clone_{int(time.time())}.wav"
        cmd = [str(VOICE), "clone", "--ref", a["ref"], a["text"], "--out", str(out)]
        if a.get("ref_text"):
            cmd += ["--ref-text", a["ref_text"]]
        return cmd
    if kind == "transcribe":
        return [str(VOICE), "transcribe", a["file"]] + (["--srt"] if a.get("srt") else [])
    if kind == "write":
        mode = a.get("mode", "prose")
        out = OUT / "text" / f"{mode}_{time.strftime('%Y%m%d_%H%M%S')}.md"
        cmd = [str(WRITE), mode]
        if mode in ("revise", "continue", "chapter"):
            cmd.append(a["file"])
            if mode == "revise": cmd += ["--note", a.get("note", "tighten and sharpen")]
            if mode == "chapter": cmd += ["--n", str(a.get("n", 1))]
        else:
            cmd.append(a["prompt"])
        for k in ("genre", "pov", "tense", "tone", "words", "chapters", "pages", "chars", "branches", "items", "temp"):
            if a.get(k) not in (None, "", False):
                cmd += [f"--{k}", str(a[k])]
        return cmd + ["--out", str(out)]
    if kind == "see":
        op = a.get("op", "describe")
        if op == "snap":
            return [str(SEE), "snap"] + (["--ask", a["question"]] if a.get("question") else [])
        if op == "ask":
            return [str(SEE), "ask", a["image"], a["question"]]
        return [str(SEE), op, a["image"]]
    raise HTTPException(400, f"unknown kind {kind}")


def _run_job(job: dict):
    log = STACK / "logs" / f"studio-job-{job['id']}.log"
    try:
        with open(log, "w") as lf:
            proc = subprocess.Popen(job["cmd"], stdout=lf, stderr=subprocess.STDOUT, env=_env(),
                                    cwd=str(STACK), start_new_session=True)
            with _jlock:
                job["pid"] = proc.pid
            rc = proc.wait()
    except Exception as exc:  # e.g. missing executable — never leave a job "running" forever
        with _jlock:
            job.update(status="failed", rc=-1, finished=time.time(), pid=None, log_tail=f"spawn failed: {exc!r}")
        return
    text = log.read_text(errors="replace")
    result = None
    for line in reversed(text.strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                result = json.loads(line)
                break
            except Exception:
                pass
    files = []
    if result and result.get("files"):
        files = result["files"]
    elif rc == 0:
        for line in text.splitlines():  # voice CLI prints the path
            s = line.strip().split(" ")[0]
            if s.startswith("/") and Path(s).exists():
                files.append(s)
    text_out = None
    if result and result.get("out") and os.path.exists(str(result["out"])):
        files.append(result["out"])
        if str(result["out"]).endswith((".md", ".txt", ".json", ".fountain", ".srt")):
            text_out = Path(result["out"]).read_text(errors="replace")[:20000]
    if result and result.get("file") and os.path.exists(str(result["file"])) and result["file"] not in files:
        files.append(result["file"])
    with _jlock:
        job.update(status="done" if rc == 0 and (result is None or result.get("ok", True)) else "failed",
                   rc=rc, finished=time.time(), result=result, files=files,
                   text=((result or {}).get("text") or text_out) if result else None,
                   log_tail=text[-1500:], pid=None)
    with open(JOBS_LOG, "a") as f:
        f.write(json.dumps({k: v for k, v in job.items() if k != "log_tail"}) + "\n")


@router.post("/run")
def run(payload: dict = Body(...)):
    kind = payload.get("kind")
    args = payload.get("args") or {}
    cmd = _build_cmd(kind, args)
    for d in ("voice", "text", "camera"):
        (OUT / d).mkdir(parents=True, exist_ok=True)
    job = {"id": uuid.uuid4().hex[:8], "kind": kind, "args": args, "cmd": cmd, "status": "running",
           "started": time.time(), "finished": None, "pid": None, "result": None, "files": [], "log_tail": ""}
    with _jlock:
        _jobs[job["id"]] = job
    threading.Thread(target=_run_job, args=(job,), daemon=True).start()
    return {"ok": True, "id": job["id"], "cmd": cmd}


@router.get("/jobs")
def jobs(limit: int = 20):
    with _jlock:
        js = sorted(_jobs.values(), key=lambda j: -j["started"])[:limit]
        out = []
        for j in js:
            d = dict(j)
            d["elapsed"] = round((j["finished"] or time.time()) - j["started"], 1)
            d["files"] = [{"path": f, "url": _url_for(f)} for f in j.get("files", [])]
            out.append(d)
    return {"jobs": out}


def _url_for(path: str) -> str | None:
    p = Path(path)
    for kind, roots in ROOTS.items():
        for d, mount in roots:
            try:
                rel = p.resolve().relative_to(d.resolve())
                return f"{mount}/{rel.as_posix()}"
            except Exception:
                continue
    return None


@router.post("/jobs/{jid}/cancel")
def cancel(jid: str):
    with _jlock:
        j = _jobs.get(jid)
    if not j:
        raise HTTPException(404)
    if j.get("pid"):
        try:
            os.killpg(j["pid"], signal.SIGTERM)
        except Exception:
            pass
    # also interrupt the ComfyUI job
    try:
        import urllib.request as u
        u.urlopen(u.Request("http://127.0.0.1:8188/interrupt", method="POST", data=b""), timeout=3)
    except Exception:
        pass
    return {"ok": True}


@router.post("/unload-all")
def unload_all(payload: dict = Body(default={})):
    """Hand unified memory back without stopping ComfyUI: /free unloads its models; the LLM and
    VLM servers hold their weights for life, so they are stopped; mlx-audio keeps every model it
    ever loaded resident, so it is restarted (if it was running). `hard: true` stops everything."""
    import panel as _panel  # same process; reuse its service control
    import urllib.request as u
    hard = bool(payload.get("hard"))
    before = _panel._mem_stats()
    steps = []
    try:
        u.urlopen(u.Request("http://127.0.0.1:8188/free", data=json.dumps({"unload_models": True, "free_memory": True}).encode(),
                            headers={"Content-Type": "application/json"}, method="POST"), timeout=10)
        steps.append("ComfyUI: models unloaded")
    except Exception as exc:
        steps.append(f"ComfyUI: not reachable ({exc.__class__.__name__})")
    for name in ("llm", "vision"):
        if _panel.read_pid(name) or _panel.port_open(_panel.SERVICES[name]["port"]):
            _panel.stop(name); steps.append(f"{name}: stopped (weights released)")
    if _panel.read_pid("audio"):
        _panel.stop("audio")
        if hard:
            steps.append("audio: stopped")
        else:
            _panel.start("audio"); steps.append("audio: restarted empty (models reload on demand)")
    if hard and _panel.read_pid("comfy"):
        _panel.stop("comfy"); steps.append("comfy: stopped")
    time.sleep(2)
    after = _panel._mem_stats()
    freed = (before.get("used", 0) - after.get("used", 0)) / 2**30
    return {"ok": True, "steps": steps, "freed_gb": round(freed, 1),
            "used_gb": round(after.get("used", 0) / 2**30, 1), "message": f"freed ~{freed:.1f} GB · " + "; ".join(steps)}


IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
VIDEO_EXT = {".mp4", ".webm", ".mov", ".mkv", ".avi", ".m4v"}


def _ffprobe(path: Path) -> dict:
    """Read a real width/height/fps/duration out of any image or video (no PIL in this venv)."""
    ff = shutil.which("ffprobe") or str(next(Path.home().glob(".hermes/tools/ffmpeg-*/ffprobe"), ""))
    if not ff:
        return {}
    r = subprocess.run([ff, "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height,r_frame_rate,duration", "-of", "json", str(path)],
                       capture_output=True, text=True)
    try:
        st = (json.loads(r.stdout or "{}").get("streams") or [{}])[0]
    except json.JSONDecodeError:
        return {}
    fps = 0.0
    rate = st.get("r_frame_rate") or "0/1"
    if "/" in rate:
        num, _, den = rate.partition("/")
        fps = float(num) / float(den) if den and float(den) else 0.0
    elif rate:
        fps = float(rate)
    return {"width": int(st.get("width") or 0), "height": int(st.get("height") or 0),
            "fps": round(fps, 3), "seconds": round(float(st.get("duration") or 0), 3)}


def _fit(w: int, h: int) -> tuple[int, int]:
    """Snap to the 16-px grid Wan's VAE wants and keep the input's aspect, long side ≤ 1280."""
    if not w or not h:
        return 0, 0
    scale = min(1.0, 1280.0 / max(w, h))
    fw, fh = max(256, int(round(w * scale / 16)) * 16), max(256, int(round(h * scale / 16)) * 16)
    return fw, fh


def _fit_frames(frames: int) -> int:
    """Wan wants length = 4k+1. Clamp to what one card can finish (9..121)."""
    k = int(round(max(9, min(121, frames)) / 4))
    return max(5, min(121, k * 4 + 1))


@router.get("/thumb")
def thumb(path: str, w: int = 320):
    """A still poster for any gallery item. The page shows these instead of a live <video>
    per tile — 48 media pipelines on one GPU is what used to kill the tab, not one bad file."""
    p = Path(path).expanduser()
    if not p.exists() or not p.is_file():
        return JSONResponse({"ok": False, "error": f"no such file: {path}"}, status_code=404)
    if p.suffix.lower() in IMAGE_EXT:
        return FileResponse(p)
    THUMBS.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(f"{p}|{p.stat().st_mtime_ns}|{w}".encode()).hexdigest()[:16]
    dst = THUMBS / f"{key}.jpg"
    if not dst.exists():
        ff = shutil.which("ffmpeg")
        if not ff:
            return JSONResponse({"ok": False, "error": "ffmpeg not found"}, status_code=500)
        for seek in ("0.5", "0"):
            subprocess.run([ff, "-y", "-loglevel", "error", *(["-ss", seek] if seek != "0" else []),
                            "-i", str(p), "-frames:v", "1", "-vf", f"scale={max(64, min(640, w))}:-2",
                            "-q:v", "5", str(dst)], check=False)
            if dst.exists():
                break
    if not dst.exists():
        return JSONResponse({"ok": False, "error": "could not read a frame"}, status_code=500)
    return FileResponse(dst, media_type="image/jpeg", headers={"Cache-Control": "max-age=600"})


@router.get("/probe")
def probe(path: str):
    """What is this input, really? Feeds the Video tab so the output matches the source format."""
    p = Path(path).expanduser()
    if not p.exists() or not p.is_file():
        return JSONResponse({"ok": False, "error": f"no such file: {path}"}, status_code=404)
    ext = p.suffix.lower()
    if ext not in IMAGE_EXT | VIDEO_EXT:
        return JSONResponse({"ok": False, "error": f"not an image or video: {p.name}"}, status_code=400)
    meta = _ffprobe(p)
    w, h = _fit(meta.get("width") or 0, meta.get("height") or 0)
    out = {"ok": True, "path": str(p), "kind": "video" if ext in VIDEO_EXT else "image",
           "width": meta.get("width"), "height": meta.get("height"), "fit_w": w, "fit_h": h,
           "fps": meta.get("fps"), "seconds": meta.get("seconds")}
    if out["kind"] == "video":
        fdir = OUT / "video" / "frames"
        fdir.mkdir(parents=True, exist_ok=True)
        frame = fdir / f"{re.sub(r'[^A-Za-z0-9_-]+', '_', p.stem)[:40]}_f000.png"
        ff = shutil.which("ffmpeg")
        if ff:
            subprocess.run([ff, "-y", "-loglevel", "error", "-ss", "0", "-i", str(p),
                            "-frames:v", "1", str(frame)], check=False)
        if frame.exists():
            out["frame"] = str(frame)
            out["frame_url"] = f"/files/output/video/frames/{frame.name}"
        src_frames = int(round((meta.get("seconds") or 0) * (meta.get("fps") or 24))) or 49
        out["fit_frames"] = _fit_frames(src_frames)
    return out


@router.post("/upload")
async def upload(request: Request):
    """Receive a browser recording or a picked file (multipart or raw body) for the Voice tab.
    Audio is converted to 24 kHz mono 16-bit WAV with ffmpeg so it works as a clone reference
    and as Whisper input. Saved under output/voice/uploads/."""
    import shutil
    from datetime import datetime
    ct = request.headers.get("content-type", "")
    name = request.query_params.get("name") or "mic"
    raw = await request.body()
    if ct.startswith("multipart/"):
        form = await request.form()
        f = form.get("file")
        if f is None:
            return JSONResponse({"ok": False, "error": "no file field"}, status_code=400)
        raw = await f.read(); name = f.filename or name
    if not raw:
        return JSONResponse({"ok": False, "error": "empty upload"}, status_code=400)
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", Path(name).stem)[:40] or "upload"
    ext = Path(name).suffix.lower()
    kind = request.query_params.get("kind") or ("image" if ext in IMAGE_EXT else
                                                "video" if ext in VIDEO_EXT else
                                                "model" if ext in {".glb", ".gltf", ".stl", ".obj", ".fbx"} else "voice")
    if kind == "video":
        # A video dropped on the Video tab stays a video — its own format is the source of truth
        # for size, fps and length, and frame 0 becomes the image-to-video start frame.
        updir = OUT / "video" / "uploads"; updir.mkdir(parents=True, exist_ok=True)
        dst = updir / f"{stem}_{datetime.now():%Y%m%d_%H%M%S}{ext if ext in VIDEO_EXT else '.mp4'}"
        dst.write_bytes(raw)
        meta = _ffprobe(dst)
        fw, fh = _fit(meta.get("width") or 0, meta.get("height") or 0)
        src_frames = int(round((meta.get("seconds") or 0) * (meta.get("fps") or 24))) or 49
        fdir = OUT / "video" / "frames"; fdir.mkdir(parents=True, exist_ok=True)
        frame = fdir / f"{dst.stem}_f000.png"
        ff = shutil.which("ffmpeg")
        if ff:
            subprocess.run([ff, "-y", "-loglevel", "error", "-ss", "0", "-i", str(dst),
                            "-frames:v", "1", str(frame)], check=False)
        return {"ok": True, "kind": "video", "path": str(dst), "url": f"/files/output/video/uploads/{dst.name}",
                "width": meta.get("width"), "height": meta.get("height"), "fps": meta.get("fps"),
                "seconds": meta.get("seconds"), "fit_w": fw, "fit_h": fh, "fit_frames": _fit_frames(src_frames),
                "frame": str(frame) if frame.exists() else None,
                "frame_url": f"/files/output/video/frames/{frame.name}" if frame.exists() else None}
    if kind == "image":
        # Images are stored as-is (converted to PNG only if the format is exotic) so they can feed gen edit / control / i2v / see.
        updir = OUT / "image" / "uploads"; updir.mkdir(parents=True, exist_ok=True)
        dst = updir / f"{stem}_{datetime.now():%Y%m%d_%H%M%S}{ext if ext in {'.png', '.jpg', '.jpeg', '.webp'} else '.png'}"
        if dst.suffix == ext:
            dst.write_bytes(raw)
        else:  # exotic format → PNG via ffmpeg (no PIL in this venv)
            tmp = dst.with_suffix(ext or ".bin"); tmp.write_bytes(raw)
            ff = shutil.which("ffmpeg") or str(next(Path.home().glob(".hermes/tools/ffmpeg-*/ffmpeg"), "ffmpeg"))
            subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(tmp), str(dst)], check=False); tmp.unlink(missing_ok=True)
        return {"ok": True, "kind": "image", "path": str(dst), "url": f"/files/output/image/uploads/{dst.name}"}
    if kind == "dataset":
        # training image → train/datasets/<dataset>/NNN.<ext> + NNN.txt caption (defaults to "[trigger]")
        ds = re.sub(r"[^A-Za-z0-9_-]+", "_", request.query_params.get("dataset") or "untitled")[:40]
        caption = request.query_params.get("caption") or "[trigger]"
        ddir = DATASETS / ds; ddir.mkdir(parents=True, exist_ok=True)
        n = len([p for p in ddir.iterdir() if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}]) + 1
        dst = ddir / f"{n:03d}{ext if ext in {'.png', '.jpg', '.jpeg', '.webp'} else '.png'}"
        dst.write_bytes(raw); dst.with_suffix(".txt").write_text(caption.strip() + "\n")
        return {"ok": True, "kind": "dataset", "dataset": ds, "path": str(dst), "count": n}
    if kind == "model":
        updir = OUT / "3d" / "uploads"; updir.mkdir(parents=True, exist_ok=True)
        dst = updir / f"{stem}_{datetime.now():%Y%m%d_%H%M%S}{ext}"
        dst.write_bytes(raw)
        return {"ok": True, "kind": "model", "path": str(dst), "url": f"/files/output/3d/uploads/{dst.name}"}
    updir = OUT / "voice" / "uploads"; updir.mkdir(parents=True, exist_ok=True)
    tmp = updir / f"{stem}_{datetime.now():%Y%m%d_%H%M%S}.src"
    tmp.write_bytes(raw)
    wav = tmp.with_suffix(".wav")
    ff = shutil.which("ffmpeg") or str(next(Path.home().glob(".hermes/tools/ffmpeg-*/ffmpeg"), "ffmpeg"))
    r = subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(tmp), "-ac", "1", "-ar", "24000", "-sample_fmt", "s16", str(wav)],
                       capture_output=True, text=True)
    tmp.unlink(missing_ok=True)
    if r.returncode != 0 or not wav.exists():
        return JSONResponse({"ok": False, "error": "ffmpeg: " + r.stderr[-300:]}, status_code=500)
    import wave
    with wave.open(str(wav)) as w:  # no ffprobe in the bundled ffmpeg dir; the header is enough
        dur = w.getnframes() / float(w.getframerate())
    return {"ok": True, "kind": "voice", "path": str(wav), "url": f"/files/output/voice/uploads/{wav.name}", "seconds": round(dur, 2)}


@router.get("/train")
def train_info():
    """Datasets (train/datasets/*) and LoRAs ComfyUI can load, for the Train tab."""
    ds = []
    if DATASETS.exists():
        for d in sorted(p for p in DATASETS.iterdir() if p.is_dir()):
            imgs = [p for p in d.iterdir() if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}]
            caps = [p for p in imgs if p.with_suffix(".txt").exists()]
            ds.append({"name": d.name, "images": len(imgs), "captioned": len(caps),
                       "sample": f"/files/train/{d.name}/{imgs[0].name}" if imgs else None})
    loras = []
    if LORAS_DIR.exists():
        for p in sorted(LORAS_DIR.glob("*.safetensors"), key=lambda p: p.stat().st_mtime, reverse=True):
            loras.append({"name": p.stem, "mb": round(p.stat().st_size / 1e6, 1), "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(p.stat().st_mtime))})
    runs = []
    rdir = STACK / "train" / "runs"
    if rdir.exists():
        for d in sorted(rdir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[:8]:
            log = d / "train.log"; tail = ""
            if log.exists():
                lines = [l for l in log.read_text(errors="replace")[-6000:].replace("\r", "\n").splitlines() if l.strip() and "it/s]" in l or "s/it" in l or "wrote" in l.lower() or "error" in l.lower()]
                tail = lines[-1].strip() if lines else ""
            runs.append({"name": d.name, "last": tail[:160], "done": (d / f"{d.name}.safetensors").exists()})
    return {"datasets": ds, "loras": loras, "runs": runs}


@router.get("/voices")
def voices():
    try:
        out = subprocess.run([str(VOICE), "voices"], capture_output=True, text=True, timeout=20, env=_env()).stdout
        return {"voices": [w.strip() for w in out.replace(",", "\n").split() if w.strip() and "_" in w]}
    except Exception as exc:
        return {"voices": ["af_heart"], "error": str(exc)}


# ───────────────────────── workflows ─────────────────────────
# One row per runnable pipeline: what it does, the entry point that runs it, and
# every weight it needs. `ready` is computed from the filesystem at request time,
# so this tab is the truth about what can run right now and what is sitting
# blocked on a missing download. Model paths are relative to ComfyUI/models/
# unless absolute.
WORKFLOWS = [
    # ---- video
    {"id": "mv_a14b", "lane": "Video", "name": "MV clips — quality",
     "what": "Stills → motion clips. Wan 2.2 I2V A14B twin-expert (high/low noise) with the lightx2v 4-step LoRAs. The default for forge/video/*/run_clips.py.",
     "tool": str(HOME / ".local" / "bin" / "pg_video"),
     "run": "pg_video --model a14b --image still.png --prompt '...' --w 960 --h 544",
     "models": ["unet/Wan2.2-I2V-A14B-HighNoise-Q6_K.gguf",
                "unet/Wan2.2-I2V-A14B-LowNoise-Q6_K.gguf",
                "loras/wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors",
                "loras/wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors",
                "text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors",
                "vae/wan_2.1_vae.safetensors"]},
    {"id": "mv_5b", "lane": "Video", "name": "MV clips — fast",
     "what": "Same job on the 5B TI2V model. Roughly a third of the model, lower fidelity — keep as the quick iteration path (MV_MODEL=5b).",
     "tool": str(HOME / ".local" / "bin" / "pg_video"),
     "run": "MV_MODEL=5b python forge/video/fc_mv/run_clips.py",
     "models": ["diffusion_models/wan2.2_ti2v_5B_fp16.safetensors",
                "text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors",
                "vae/wan2.2_vae.safetensors"]},
    {"id": "sing_video_s2v", "lane": "Video", "name": "Singing video — lipsync",
     "what": "One reference image + an audio track → a lip-synced performance. This is the model that makes the character actually sing your song.",
     "tool": None,
     "run": "ComfyUI template: video_wan2_2_s2v (image + audio → video)",
     "models": ["diffusion_models/wan2.2_s2v_14B_fp8_scaled.safetensors",
                "audio_encoders/wav2vec2_large_english_fp16.safetensors",
                "text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors",
                "vae/wan_2.1_vae.safetensors"]},
    {"id": "animate2", "lane": "Video", "name": "Character animation — motion transfer",
     "what": "A reference image says WHO, a driving video says WHAT MOTION, the prompt says background + camera. No pose extraction. Holds identity across shots.",
     "tool": None,
     "run": "ComfyUI template: video_wan_animate2",
     "models": ["diffusion_models/wan_animate_2_int8_convrot.safetensors",
                "clip_vision/clip_vision_h.safetensors",
                "loras/lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors",
                "text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors",
                "vae/wan_2.1_vae.safetensors"]},
    {"id": "clip_restore", "lane": "Video", "name": "Clip restore — SeedVR2",
     "what": "Render at 544p, restore to 1080p-class. 1-step diffusion upscale; the cheapest real quality jump on a finished clip.",
     "tool": str(HOME / ".local" / "bin" / "pg_upscale"),
     "run": "pg_upscale --video clips/s01.mp4 --scale 2",
     "models": ["diffusion_models/seedvr2_3b_int8_convrot.safetensors",
                "vae/seedvr2_ema_vae_fp16.safetensors"]},
    {"id": "hyv15_i2v", "lane": "Video", "name": "High-quality i2v — HunyuanVideo 1.5",
     "what": "8.3B cfg-distilled 720p image-to-video. The slower, more cinematic alternative to the Wan clips.",
     "tool": str(GEN),
     "run": "gen video --model hyv15 --image start.png --prompt '...'",
     "models": ["diffusion_models/hunyuanvideo1.5_720p_i2v_cfg_distilled_fp16.safetensors",
                "clip_vision/sigclip_vision_patch14_384.safetensors",
                "text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors",
                "text_encoders/byt5_small_glyphxl_fp16.safetensors",
                "vae/hunyuanvideo15_vae_fp16.safetensors"]},
    {"id": "ltx720", "lane": "Video", "name": "LTX-Video 2B — 720p-class",
     "what": "Fast true-motion img2vid/text2vid on the LTX 2B checkpoint. Lighter and quicker than Wan, less photoreal.",
     "tool": str(HOME / ".local" / "bin" / "ltx720"),
     "run": "ltx720 'prompt' --hero still.png --w 768 --h 512",
     "models": ["checkpoints/ltx-video-2b-v0.9.safetensors",
                "text_encoders/t5xxl_fp16.safetensors"]},
    {"id": "infinitetalk", "lane": "Video", "name": "Talking head — InfiniteTalk (legacy)",
     "what": "Image + audio → lip-synced talking clip via the Multitalk adapter on Wan 2.1. Superseded by S2V for singing; kept for the 480p path.",
     "tool": str(HOME / ".local" / "bin" / "infinitetalk_run"),
     "run": "infinitetalk_run --image rapper.jpg --audio vocal.wav --prompt '...'",
     "models": ["diffusion_models/infinitetalk_single.safetensors",
                "diffusion_models/wan2.1-i2v-14b-480p-Q4_K_M.gguf",
                "clip_vision/CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors",
                "text_encoders/umt5_xxl_fp16.safetensors",
                "vae/wan_2.1_vae.safetensors"]},
    # ---- image
    {"id": "stills_krea2", "lane": "Image", "name": "MV stills — Krea 2 turbo",
     "what": "The stills that seed every MV shot. Krea 2 turbo at 8 steps, cfg 1.",
     "tool": str(HOME / "forge" / "video" / "fc_mv" / "run_stills.py"),
     "run": "python forge/video/fc_mv/run_stills.py",
     "models": ["diffusion_models/krea2_turbo_fp8_scaled.safetensors",
                "text_encoders/qwen3vl_4b_fp8_scaled.safetensors",
                "vae/qwen_image_vae.safetensors"]},
    {"id": "image_gen", "lane": "Image", "name": "Image generate — Flux / Z-Image",
     "what": "General stills. Z-Image turbo for speed, Flux dev fp8 for quality.",
     "tool": str(GEN),
     "run": "gen image 'prompt' --model zimage",
     "models": ["diffusion_models/z_image_turbo_bf16.safetensors",
                "text_encoders/qwen_3_4b.safetensors",
                "vae/ae.safetensors",
                "checkpoints/flux1-dev-fp8.safetensors"]},
    {"id": "image_edit", "lane": "Image", "name": "Image edit — Qwen-Image-Edit",
     "what": "Instruction editing that keeps the subject: turnarounds, wardrobe changes, A-pose sheets. --fast uses the 4-step Lightning LoRA.",
     "tool": str(GEN),
     "run": "gen edit in.png 'instruction' --fast",
     "models": ["diffusion_models/qwen_image_edit_2509_fp8_e4m3fn.safetensors",
                "loras/Qwen-Image-Edit-2509-Lightning-4steps-V1.0-bf16.safetensors",
                "loras/Qwen-Edit-2509-Multiple-angles.safetensors",
                "text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors",
                "vae/qwen_image_vae.safetensors"]},
    # ---- audio / singing
    {"id": "song_xl", "lane": "Singing", "name": "Full songs — ACE-Step 1.5 XL",
     "what": "The quality tier for generated songs: 4B DiT decoder, 44 steps, cfg 5. Best open vocal/mix scores of the ACE-Step family.",
     "tool": str(HOME / ".local" / "bin" / "ace_song"),
     "run": "ace_song 'tags' --lyrics-file song.txt --seconds 180",
     "models": ["diffusion_models/acestep_v1.5_xl_sft_bf16.safetensors",
                "text_encoders/qwen_0.6b_ace15.safetensors",
                "text_encoders/qwen_1.7b_ace15.safetensors",
                "vae/ace_1.5_vae.safetensors"]},
    {"id": "song_turbo", "lane": "Singing", "name": "Full songs — ACE-Step 1.5 turbo",
     "what": "Same family, 8 steps / cfg 1 — for when you want a bed or a draft in seconds rather than the best take.",
     "tool": str(HOME / ".local" / "bin" / "ace_music"),
     "run": "ace_music 'tags' --seconds 60",
     "models": ["diffusion_models/acestep_v1.5_turbo.safetensors",
                "text_encoders/qwen_0.6b_ace15.safetensors",
                "text_encoders/qwen_1.7b_ace15.safetensors",
                "vae/ace_1.5_vae.safetensors"]},
    {"id": "song_aio", "lane": "Singing", "name": "Full songs — ACE-Step AIO",
     "what": "The all-in-one checkpoint the model card documents (LM + DiT + VAE in one file). Turbo semantics: 8 steps, cfg 1.",
     "tool": str(HOME / ".local" / "bin" / "ace_aio"),
     "run": "ace_aio --lyrics-file song.txt --tags 'rap, male rapper' --seconds 180",
     "models": ["checkpoints/ace_step_1.5_turbo_aio.safetensors"]},
    {"id": "song_diffrhythm2", "lane": "Singing", "name": "Songs — DiffRhythm 2",
     "what": "Block-flow-matching full songs with tight lyric alignment. Drives the forge/audio/rap_v2 take harness (multi-take + STT scoring).",
     "tool": str(HOME / "forge" / "audio" / "DiffRhythm2" / "inference.py"),
     "run": "cd forge/audio/DiffRhythm2 && bash inference.sh",
     "models": [str(HOME / "forge" / "audio" / "DiffRhythm2" / "ckpt" / "model.safetensors"),
                str(HOME / "forge" / "audio" / "DiffRhythm2" / "ckpt" / "decoder.bin")]},
    {"id": "svc_soulx", "lane": "Singing", "name": "Song re-voice — SVC pipeline",
     "what": "The whole chain in one command: separates the song's lead vocal from its backing, converts that vocal to a reference voice's timbre, then remixes with the ORIGINAL backing. Keeps melody, timing and lyrics; fixes thin/inconsistent AI vocals.",
     "tool": str(HOME / ".local" / "bin" / "svc_song"),
     "run": "svc_song --song master.mp3 --voice ref.wav [--pitch-shift -2]",
     "models": ["/home/billie/forge/audio/SoulX-Singer/pretrained_models/SoulX-Singer/model-svc.pt",
                "/home/billie/forge/audio/SoulX-Singer/pretrained_models/SoulX-Singer/model.pt",
                "/home/billie/forge/audio/SoulX-Singer/pretrained_models/SoulX-Singer-Preprocess/rmvpe/rmvpe.pt",
                "/home/billie/forge/audio/SoulX-Singer/pretrained_models/SoulX-Singer-Preprocess/mel-band-roformer-karaoke/mel_band_roformer_karaoke_becruily.ckpt",
                "/home/billie/forge/audio/SoulX-Singer/pretrained_models/SoulX-Singer-Preprocess/dereverb_mel_band_roformer/dereverb_mel_band_roformer_anvuew_sdr_19.1729.ckpt"]},
    {"id": "sfx_sa3", "lane": "Singing", "name": "SFX + music beds — Stable Audio 3",
     "what": "Text-to-audio for sound design and instrumental beds (no lyrics — use ACE-Step for sung words).",
     "tool": str(GEN),
     "run": "gen sfx 'thunder, rain on a tin roof' --seconds 12",
     "models": ["checkpoints/stable_audio_3_medium.safetensors",
                "checkpoints/stable_audio_3_small_sfx.safetensors",
                "text_encoders/t5gemma_b_b_ul2.safetensors"]},
]


@router.get("/workflows")
def workflows():
    """Every workflow the stack knows, with a live ready/blocked verdict."""
    out = []
    for w in WORKFLOWS:
        files = []
        for rel in w["models"]:
            fp = Path(rel).expanduser()
            if not fp.is_absolute():
                fp = MODELS / rel
            ok = fp.is_file()
            files.append({"rel": rel, "name": fp.name, "present": ok,
                          "gb": round(fp.stat().st_size / 1e9, 2) if ok else None})
        tool = w.get("tool")
        tool_ok = None
        if tool:
            tp = Path(tool)
            # Presence is what matters. Several entry points are invoked as
            # `bash foo.sh` or `python foo.py` and never carry the exec bit, so
            # requiring +x reported working workflows as blocked.
            tool_ok = tp.is_file()
        missing = [f["name"] for f in files if not f["present"]]
        out.append({"id": w["id"], "lane": w["lane"], "name": w["name"],
                    "what": w["what"], "run": w.get("run", ""),
                    "tool": tool, "tool_present": tool_ok,
                    "models": files, "missing": missing,
                    "ready": (not missing) and (tool_ok is not False)})
    lanes = [{"lane": ln, "items": [x for x in out if x["lane"] == ln]}
             for ln in dict.fromkeys(w["lane"] for w in WORKFLOWS)]
    return {"lanes": lanes, "total": len(out),
            "ready": sum(1 for x in out if x["ready"]),
            "blocked": [x["name"] for x in out if not x["ready"]]}