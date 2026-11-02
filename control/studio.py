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
import os
import re
import shutil
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import JSONResponse

HOME = Path.home()
STACK = HOME / "media-stack"
OUT = STACK / "output"
COMFY_OUT = STACK / "ComfyUI" / "output"
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
FFMPEG = next((p for p in (HOME / ".hermes" / "tools").glob("ffmpeg-*/ffmpeg")), None)

router = APIRouter(prefix="/api/studio")

# ───────────────────────── inventory ─────────────────────────
TOOLS = [
    ("gen", GEN, "ComfyUI pipelines: image / control / upscale / video / sfx / music"),
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
    "text": {".md", ".txt", ".json", ".fountain"},
    "camera": {".jpg", ".jpeg", ".png"},
}
# where each modality's files live; (dir, url mount)
ROOTS = {
    "image": [(OUT / "image", "/files/output/image"), (OUT / "control", "/files/output/control"),
              (OUT / "upscale", "/files/output/upscale"), (COMFY_OUT, "/files/comfy_output")],
    "video": [(OUT / "video", "/files/output/video"), (OUT / "image" / "uploads", "/files/output/image/uploads"), (COMFY_OUT / "video", "/files/comfy_output/video"),
              (STACK / "scratch" / "video-test", "/files/scratch/video-test")],
    "sound": [(OUT / "sfx", "/files/output/sfx"), (OUT / "music", "/files/output/music"), (OUT / "stems", "/files/output/stems"),
              (COMFY_OUT / "audio", "/files/comfy_output/audio"), (STACK / "scratch", "/files/scratch")],
    "voice": [(OUT / "voice", "/files/output/voice"), (STACK / "scratch" / "voice-test", "/files/scratch/voice-test")],
    "text": [(OUT / "text", "/files/output/text")],
    "camera": [(OUT / "camera", "/files/output/camera"), (OUT / "image", "/files/output/image")],
    "3d": [(STACK / "vr", "/vr"), (COMFY_OUT / "3d", "/files/comfy_output/3d"), (OUT / "3d", "/files/output/3d"),
           (STACK / "scratch" / "print-test", "/files/scratch/print-test"), (STACK / "scratch" / "vr-test", "/files/scratch/vr-test")],
}


@router.get("/outputs")
def outputs(kind: str = "image", limit: int = 48):
    if kind not in ROOTS:
        raise HTTPException(400, "unknown kind")
    exts = EXT[kind]
    seen, items = set(), []
    for d, mount in ROOTS[kind]:
        if not d.is_dir():
            continue
        for p in d.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in exts or ".part" in p.name:
                continue
            rp = p.resolve()
            if rp in seen:
                continue
            seen.add(rp)
            st = p.stat()
            rel = p.relative_to(d).as_posix()
            items.append({"name": p.name, "path": str(p), "url": f"{mount}/{rel}", "bytes": st.st_size,
                          "mtime": st.st_mtime, "when": time.strftime("%m-%d %H:%M", time.localtime(st.st_mtime)),
                          "ext": p.suffix.lower().lstrip(".")})
    items.sort(key=lambda x: -x["mtime"])
    return {"kind": kind, "items": items[:limit]}


# ───────────────────────── ComfyUI progress (websocket listener) ─────────────────────────
# ComfyUI sends execution_start / executing / progress only to the socket whose clientId
# submitted the prompt. `gen` and the Hermes image_gen plugin both submit as "gen-cli", so
# the panel connects under that id and receives their step-by-step progress.
_progress = {"connected": False, "prompt_id": None, "node": None, "value": 0, "max": 0,
             "status": "idle", "started": None, "updated": None, "queue_remaining": 0, "last_node_type": None}
_plock = threading.Lock()


def _ws_loop():
    try:
        import websocket  # websocket-client
    except Exception:
        return
    while True:
        try:
            ws = websocket.create_connection("ws://127.0.0.1:8188/ws?clientId=gen-cli", timeout=5)
            ws.settimeout(30)
            with _plock:
                _progress["connected"] = True
            while True:
                try:
                    raw = ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                if not isinstance(raw, str):
                    continue
                msg = json.loads(raw)
                t, d = msg.get("type"), msg.get("data", {})
                now = time.time()
                with _plock:
                    _progress["updated"] = now
                    if t == "status":
                        _progress["queue_remaining"] = d.get("status", {}).get("exec_info", {}).get("queue_remaining", 0)
                        if _progress["queue_remaining"] == 0 and _progress["status"] != "running":
                            _progress["status"] = "idle"
                    elif t == "execution_start":
                        _progress.update(prompt_id=d.get("prompt_id"), status="running", started=now, value=0, max=0, node=None)
                    elif t == "executing":
                        if d.get("node") is None:
                            _progress.update(status="done", node=None, value=_progress["max"] or 1, max=_progress["max"] or 1)
                        else:
                            _progress["node"] = d.get("node")
                    elif t == "progress":
                        _progress.update(value=d.get("value", 0), max=d.get("max", 0), node=d.get("node"), status="running")
                    elif t in ("execution_error",):
                        _progress.update(status="error", node=None)
                    elif t == "execution_interrupted":
                        _progress.update(status="interrupted", node=None)
        except Exception:
            with _plock:
                _progress["connected"] = False
            time.sleep(3)


threading.Thread(target=_ws_loop, daemon=True, name="comfy-ws").start()


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
        if a.get("lora"):
            cmd += ["--lora", f"{a['lora']}:{a.get('lora_strength') or 1.0}"]
        return cmd
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
        return [str(GEN), "video", a["prompt"], *flag("--image"), *flag("--w", cast=int), *flag("--h", cast=int),
                *flag("--frames", cast=int), *flag("--fps", cast=int), *flag("--steps", cast=int), *flag("--seed", cast=int)]
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
    kind = request.query_params.get("kind") or ("image" if ext in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"} else
                                                "model" if ext in {".glb", ".gltf", ".stl", ".obj", ".fbx"} else "voice")
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