#!/usr/bin/env python3
"""Local media-stack control panel — one origin (:8787).

  /          Studio page (control/studio.html + studio.py): Image / Video / 3D & VR /
             Sound / Voice run forms, live ComfyUI progress bar, output galleries with
             inline preview, Models inventory, Services, Resources
  /vr/       WebXR asset room (index.html?src=…&rig=1 = any GLB + joint picker), GLB/STL viewer (view.html)

Run:  ~/media-stack/audio/.venv/bin/python ~/media-stack/control/panel.py
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

from fastapi import Body, FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

HOME = Path.home()
STACK = HOME / "media-stack"
LOGS = STACK / "logs"
RUN = STACK / "run"
COMFY = STACK / "ComfyUI"
VR = STACK / "vr"
AUDIO_PY = STACK / "audio" / ".venv" / "bin" / "python"
LLM_PY = STACK / "llm" / ".venv" / "bin" / "python"
# Local language + vision models (MLX). Uncensored writer and an image-understanding VLM.
LLM_MODEL = os.environ.get("LLM_MODEL", "mlx-community/Qwen3.8-27B-Uncensored-OptiQ-4bit")
VLM_MODEL = os.environ.get("VLM_MODEL", "mlx-community/Qwen3-VL-8B-Instruct-4bit")

for d in (LOGS, RUN, VR):
    d.mkdir(parents=True, exist_ok=True)

FFMPEG_DIR = HOME / ".hermes" / "tools"
FFMPEG = next((p for p in FFMPEG_DIR.glob("ffmpeg-*/ffmpeg")), None)


def _base_env() -> dict:
    env = os.environ.copy()
    if FFMPEG is not None:
        env["PATH"] = f"{FFMPEG.parent}:{env.get('PATH', '')}"
    env["PYTHONUNBUFFERED"] = "1"
    return env


SERVICES = {
    "comfy": {
        "label": "ComfyUI",
        "port": 8188,
        "cmd": [str(COMFY / ".venv" / "bin" / "python"), "main.py",
                "--listen", "127.0.0.1", "--port", "8188"],
        "cwd": str(COMFY),
        "desc": "Image, video + 3D generation (diffusion)",
    },
    "audio": {
        "label": "mlx-audio",
        "port": 8000,
        "cmd": [str(AUDIO_PY), "-m", "mlx_audio.server", "--host", "127.0.0.1", "--port", "8000"],
        "cwd": str(STACK / "audio"),
        "desc": "TTS, STT, music + SFX (MLX)",
    },
    "llm": {
        "label": "writer LLM",
        "port": 8081,
        "cmd": [str(LLM_PY), "-m", "mlx_lm.server", "--host", "127.0.0.1", "--port", "8081", "--model", LLM_MODEL],
        "cwd": str(STACK / "llm"),
        "desc": f"OpenAI-compatible chat · {LLM_MODEL.split('/')[-1]} (uncensored, ~16 GB)",
    },
    "vision": {
        "label": "vision VLM",
        "port": 8082,
        "cmd": [str(LLM_PY), "-m", "mlx_vlm.server", "--host", "127.0.0.1", "--port", "8082", "--model", VLM_MODEL],
        "cwd": str(STACK / "llm"),
        "desc": f"image understanding · {VLM_MODEL.split('/')[-1]} (~5 GB)",
    },
}


def lan_ip() -> str | None:
    """This machine's LAN address (no packets sent — UDP connect only picks a route)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("1.1.1.1", 80))
        return s.getsockname()[0]
    except Exception:
        return None
    finally:
        s.close()


KOKORO = "mlx-community/Kokoro-82M-bf16"
CLONE_MODEL = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16"
STT_MODEL = "mlx-community/parakeet-tdt-0.6b-v3"

# Every row is a URL another local program/page can be pointed at. `path` is appended to
# http://<host>:<port>. Keep this the single source of truth — the Resources tab renders it.
ENDPOINTS = [
    {
        "key": "tts", "label": "TTS · text → speech", "svc": "audio", "port": 8000,
        "env": "VF_TTS", "path": "/v1/audio/speech",
        "desc": "OpenAI-compatible speech endpoint (Kokoro 82M, 50+ voices). POST JSON, get audio bytes back.",
        "paths": [("POST", "/v1/audio/speech", "JSON {model, voice, input, speed, response_format}"),
                  ("GET", f"/v1/audio/voices?model={KOKORO}", "voice ids you can pass as voice")],
        "snippet": (
            "curl -s -X POST {{base}} -H 'Content-Type: application/json' \\\n"
            f"  -d '{{\"model\":\"{KOKORO}\",\"voice\":\"af_heart\",\"input\":\"Hello from the forge\",\"response_format\":\"wav\"}}' \\\n"
            "  -o hello.wav"
        ),
    },
    {
        "key": "stt", "label": "STT · speech → text", "svc": "audio", "port": 8000,
        "env": "VF_STT", "path": "/v1/audio/transcriptions",
        "desc": "OpenAI-compatible transcription (Parakeet 0.6B v3 default; pass a Whisper repo id for other languages).",
        "paths": [("POST", "/v1/audio/transcriptions", "multipart: file, model, language?, response_format"),
                  ("GET", "/openapi.json", "live schema for every mlx-audio route")],
        "snippet": (
            "curl -s -X POST {{base}} \\\n"
            f"  -F file=@clip.wav -F model={STT_MODEL} -F response_format=text"
        ),
    },
    {
        "key": "clone", "label": "Voice clone (Qwen3-TTS)", "svc": "audio", "port": 8000,
        "env": "VF_CLONE", "path": "/v1/audio/speech",
        "desc": "Same speech endpoint — add ref_audio (a wav on this Mac) and the ref_text it says.",
        "paths": [("POST", "/v1/audio/speech", "JSON + ref_audio, ref_text")],
        "snippet": (
            "curl -s -X POST {{base}} -H 'Content-Type: application/json' \\\n"
            f"  -d '{{\"model\":\"{CLONE_MODEL}\",\"input\":\"New line in your voice\",\"ref_audio\":\"ref.wav\",\"ref_text\":\"the words in the reference\",\"response_format\":\"wav\"}}' \\\n"
            "  -o clone.wav"
        ),
    },
    {
        "key": "comfy", "label": "ComfyUI · image / video / 3D / sfx / music", "svc": "comfy", "port": 8188,
        "env": "VF_COMFY", "path": "",
        "desc": "Everything diffusion. Submit your own graph as {\"prompt\": {…}} then poll /history/{id}.",
        "paths": [("POST", "/prompt", "{\"prompt\": <api graph>, \"client_id\": \"<id>\"} → {\"prompt_id\": …}"),
                  ("GET", "/history/{prompt_id}", "outputs once the job leaves the queue"),
                  ("GET", "/view?filename=…&subfolder=…&type=output", "fetch a produced file"),
                  ("GET", "/object_info", "every node + its accepted parameters"),
                  ("GET", "/queue", "running / pending"),
                  ("WS", "/ws?clientId=<same id>", "progress events — only to the submitting client id")],
        "snippet": (
            "curl -s {{base_origin}}/object_info | python3 -c 'import json,sys;d=json.load(sys.stdin);print(len(d),\"nodes\")'\n"
            "curl -s -X POST {{base_origin}}/prompt -H 'Content-Type: application/json' -d @workflow.json   # workflow.json = {\"prompt\": {...}}"
        ),
    },
    {
        "key": "llm", "label": "Writer LLM (OpenAI-compatible chat)", "svc": "llm", "port": 8081,
        "env": "VF_LLM", "path": "/v1",
        "desc": f"{LLM_MODEL.split('/')[-1]} · uncensored, ~16 GB. Drop-in for the OpenAI SDK base_url.",
        "paths": [("POST", "/v1/chat/completions", "standard OpenAI chat body; add chat_template_kwargs.enable_thinking=false"),
                  ("GET", "/v1/models", "loaded model id")],
        "snippet": (
            "curl -s {{base}}/chat/completions -H 'Content-Type: application/json' \\\n"
            f"  -d '{{\"model\":\"{LLM_MODEL}\",\"messages\":[{{\"role\":\"user\",\"content\":\"hi\"}}],\"chat_template_kwargs\":{{\"enable_thinking\":false}}}}'"
        ),
    },
    {
        "key": "vision", "label": "Vision VLM (image understanding)", "svc": "vision", "port": 8082,
        "env": "VF_VISION", "path": "/v1",
        "desc": f"{VLM_MODEL.split('/')[-1]} · ~5 GB. Same chat shape; content parts carry an image_url (a data: URL or an http/file URL).",
        "paths": [("POST", "/v1/chat/completions", "messages[].content = [{type:text},{type:image_url}]"),
                  ("GET", "/v1/models", "loaded model id")],
        "snippet": (
            "curl -s {{base}}/chat/completions -H 'Content-Type: application/json' \\\n"
            f"  -d '{{\"model\":\"{VLM_MODEL}\",\"messages\":[{{\"role\":\"user\",\"content\":[{{\"type\":\"text\",\"text\":\"what is in this image?\"}},{{\"type\":\"image_url\",\"image_url\":{{\"url\":\"data:image/png;base64,<BASE64>\"}}}}]}}],\"chat_template_kwargs\":{{\"enable_thinking\":false}}}}'"
        ),
    },
    {
        "key": "panel", "label": "Studio API (jobs, status, files)", "svc": "panel", "port": 8787,
        "env": "VF_PANEL", "envsuffix": "", "path": "/api/status",
        "desc": "This page's own API: service health, job list, outputs, uploads, unload-all.",
        "paths": [("GET", "/api/status", "services + installed models"),
                  ("GET", "/api/resources", "cpu / gpu / mem / swap / disk"),
                  ("GET", "/api/studio/jobs", "job list"),
                  ("POST", "/api/studio/unload-all", "free memory ({\"hard\":true} = stop services)"),
                  ("GET", "/files/output/image/<file>", "any generated file by path")],
        "snippet": "curl -s {{base}} | python3 -m json.tool | head -40",
    },
]


def port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) == 0


def pidfile(name: str) -> Path:
    return RUN / f"{name}.pid"


def read_pid(name: str) -> int | None:
    p = pidfile(name)
    if not p.exists():
        return None
    try:
        pid = int(p.read_text().strip())
    except Exception:
        return None
    try:
        os.kill(pid, 0)
    except OSError:
        p.unlink(missing_ok=True)
        return None
    return pid


def _engines() -> dict:
    """Last probe written by forge-recommend. Empty if this machine has not been probed yet."""
    path = STACK / "run" / "forge-engines.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data.get("engines") or {}


def _service_launch(name: str) -> tuple[dict, dict, str | None]:
    """Return (service copy, env, error). The engine map picks CUDA, ROCm, MLX, or a stand-in."""
    svc = dict(SERVICES[name])
    svc["cmd"] = list(svc["cmd"])
    env = _base_env()
    eng = _engines()
    if not eng:
        return svc, env, None
    backend = eng.get("backend") or "mlx"
    if name == "comfy":
        if backend in ("cuda", "rocm") and eng.get("gpu_index") is not None:
            env["CUDA_VISIBLE_DEVICES"] = str(eng["gpu_index"])
        if backend == "cpu":
            svc["cmd"].append("--cpu")
        return svc, env, None
    if name == "audio" and backend != "mlx":
        speaches = shutil.which("speaches")
        if not speaches:
            return svc, env, "Voice on this machine is speaches (not MLX), and speaches is not on PATH. See INSTALL-UBUNTU.md section 5."
        env["UVICORN_HOST"] = "127.0.0.1"
        env["UVICORN_PORT"] = "8000"
        svc["cmd"] = [speaches]
        svc["label"] = "speaches"
        svc["desc"] = "TTS and STT (speaches)"
        return svc, env, None
    if name == "llm":
        slot = eng.get("llm") or {}
        if slot.get("engine") == "llama-server":
            binary = os.environ.get("LLAMA_SERVER") or shutil.which("llama-server")
            model = os.environ.get("WRITER_GGUF") or slot.get("model") or ""
            if not binary or not model or not Path(model).exists():
                return svc, env, "Writer here is llama-server. Set LLAMA_SERVER if needed and WRITER_GGUF to a local GGUF. VF_UNCENSORED=1 selects the labeled uncensored writer. See INSTALL-UBUNTU.md section 6."
            svc["cmd"] = [binary, "-m", model, "--host", "127.0.0.1", "--port", "8081"]
            svc["label"] = "writer (llama-server)"
            return svc, env, None
        model = os.environ.get("LLM_MODEL") or slot.get("model") or ""
        if not model:
            return svc, env, "No writer model selected. Export LLM_MODEL, or VF_UNCENSORED=1 for the labeled uncensored Qwen."
        svc["cmd"] = [str(LLM_PY), "-m", "mlx_lm.server", "--host", "127.0.0.1", "--port", "8081", "--model", model]
        if os.environ.get("VF_UNCENSORED") == "1" or "Uncensored" in model or "uncensored" in model:
            svc["desc"] = "labeled uncensored writer"
        return svc, env, None
    if name == "vision" and backend != "mlx":
        binary = os.environ.get("LLAMA_SERVER") or shutil.which("llama-server")
        model = os.environ.get("VLM_GGUF") or ""
        mmproj = os.environ.get("VLM_MMPROJ") or ""
        if not binary or not model or not mmproj:
            return svc, env, "Vision here is llama-server with a VLM GGUF and mmproj. Set VLM_GGUF and VLM_MMPROJ. See INSTALL-UBUNTU.md section 6."
        svc["cmd"] = [binary, "-m", model, "--mmproj", mmproj, "--host", "127.0.0.1", "--port", "8082"]
        svc["label"] = "vision (llama-server)"
        return svc, env, None
    return svc, env, None


def start(name: str) -> dict:
    base = SERVICES[name]
    if read_pid(name) or port_open(base["port"]):
        return {"ok": True, "already": True, "message": f"{base['label']} already running"}
    svc, env, err = _service_launch(name)
    if err:
        return {"ok": False, "message": err}
    log = LOGS / f"{name}.log"
    fh = open(log, "ab")
    fh.write(f"\n=== start {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n".encode())
    fh.flush()
    proc = subprocess.Popen(
        svc["cmd"], cwd=svc["cwd"], stdout=fh, stderr=subprocess.STDOUT,
        env=env, start_new_session=True,
    )
    pidfile(name).write_text(str(proc.pid))
    return {"ok": True, "pid": proc.pid, "message": f"{svc['label']} starting on :{svc['port']}"}


def stop(name: str) -> dict:
    svc = SERVICES[name]
    pid = read_pid(name)
    if not pid:
        return {"ok": True, "already": True, "message": f"{svc['label']} not running"}
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except OSError:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    for _ in range(50):
        if not read_pid(name):
            break
        time.sleep(0.1)
    else:
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except OSError:
            pass
    pidfile(name).unlink(missing_ok=True)
    return {"ok": True, "message": f"{svc['label']} stopped"}


def tail(name: str, lines: int = 40) -> str:
    p = LOGS / f"{name}.log"
    if not p.exists():
        return ""
    try:
        return "\n".join(p.read_text(errors="replace").splitlines()[-lines:])
    except Exception as exc:
        return f"<log unreadable: {exc}>"


def comfy_checkpoints() -> list[str]:
    d = COMFY / "models" / "checkpoints"
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.iterdir() if p.suffix in {".safetensors", ".ckpt", ".pt"})


def comfy_loras() -> list[str]:
    d = COMFY / "models" / "loras"
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.iterdir() if p.suffix == ".safetensors")


def hf_cached(repo: str) -> bool:
    d = HOME / ".cache" / "huggingface" / "hub" / ("models--" + repo.replace("/", "--"))
    return d.is_dir()


AUDIO_MODELS = [
    ("tts", "mlx-community/Kokoro-82M-bf16", "Kokoro 82M", "fast, 8 languages — TTS default"),
    ("tts", "mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-bf16", "Qwen3-TTS 1.7B", "voice design, 10+ languages"),
    ("tts", "mlx-community/chatterbox-multilingual-v3", "Chatterbox v3", "expressive, 23 languages"),
    ("stt", "mlx-community/whisper-large-v3-turbo-asr-fp16", "Whisper large-v3 turbo", "99 languages — STT default"),
    ("stt", "mlx-community/parakeet-tdt-0.6b-v3", "Parakeet 0.6B v3", "fast English + 25 EU"),
    ("music", "mlx-community/MiniMax-Music3-8bit", "MiniMax Music 3", "full songs with lyrics, 44.1kHz stereo"),
]


def stack_status() -> dict:
    out = {}
    for name, svc in SERVICES.items():
        pid = read_pid(name)
        out[name] = {
            "label": svc["label"], "port": svc["port"], "desc": svc["desc"],
            "pid": pid, "running": bool(pid) or port_open(svc["port"]),
            "responding": port_open(svc["port"]),
        }
    return out


# ── resource sampling ────────────────────────────────────────────────────
def _run(cmd: list[str], timeout: float = 3.0) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ""


_PS_CACHE: dict = {"at": 0.0, "value": {}}
_RES_CACHE: dict = {"at": 0.0, "value": {}}
_RES_TTL = 1.2


def _gpu_stats() -> dict:
    """GPU utilisation via ioreg's IOAccelerator PerformanceStatistics (no root needed)."""
    raw = _run(["ioreg", "-r", "-d", "1", "-w", "0", "-c", "IOAccelerator"])
    m = re.search(r'"PerformanceStatistics"\s*=\s*(\{.*?\})\s*\n', raw)
    if not m:
        return {"available": False}
    body = m.group(1)
    vals = dict(re.findall(r'"([^"]+)"\s*=\s*(-?\d+)', body))
    out = {"available": True}
    if "Device Utilization %" in vals:
        out["util"] = int(vals["Device Utilization %"])
    if "Renderer Utilization %" in vals:
        out["renderer"] = int(vals["Renderer Utilization %"])
    if "Tiler Utilization %" in vals:
        out["tiler"] = int(vals["Tiler Utilization %"])
    if "In use system memory" in vals:
        out["mem_used"] = int(vals["In use system memory"])
    if "Alloc system memory" in vals:
        out["mem_alloc"] = int(vals["Alloc system memory"])
    return out


def _cpu_stats() -> dict:
    out = {}
    raw = _run(["top", "-l", "1", "-n", "0", "-s", "0"], timeout=4.0)
    m = re.search(r"CPU usage:\s*([\d.]+)% user,\s*([\d.]+)% sys,\s*([\d.]+)% idle", raw)
    if m:
        user, sys_, idle = (float(x) for x in m.groups())
        out.update({"user": user, "sys": sys_, "idle": idle, "busy": round(100 - idle, 1)})
    m = re.search(r"Load Avg:\s*([\d.]+),\s*([\d.]+),\s*([\d.]+)", raw)
    if m:
        out["load"] = [float(x) for x in m.groups()]
    return out


def _mem_stats() -> dict:
    total = 0
    try:
        total = int(_run(["sysctl", "-n", "hw.memsize"]).strip())
    except Exception:
        pass
    page = 16384
    s: dict[str, int] = {}
    vm = _run(["vm_stat"])
    for line in vm.splitlines():
        if "page size of" in line:
            mm = re.search(r"page size of (\d+) bytes", line)
            if mm:
                page = int(mm.group(1))
        if ":" in line:
            k, v = line.split(":", 1)
            digits = re.sub(r"[^\d]", "", v)
            if digits:
                s[k.strip()] = int(digits)
    free = (s.get("Pages free", 0) + s.get("Pages speculative", 0)) * page
    wired = s.get("Pages wired down", 0) * page
    compressed = s.get("Pages occupied by compressor", 0) * page
    active = s.get("Pages active", 0) * page
    swap = {}
    sw = _run(["sysctl", "-n", "vm.swapusage"])

    def _mb(num: str, unit: str) -> int:
        return int(float(num) * (1024**2 if unit == "M" else 1024**3))
    for k, num, unit in re.findall(r"(\w+)\s*=\s*([\d.]+)([MG])", sw):
        swap[k] = _mb(num, unit)
    return {
        "total": total,
        "free": free,
        "used": max(total - free, 0),
        "wired": wired,
        "compressed": compressed,
        "active": active,
        "swap_total": swap.get("total", 0),
        "swap_used": swap.get("used", 0),
    }


def _top_procs(limit: int = 8) -> list[dict]:
    now = time.monotonic()
    if now - _PS_CACHE["at"] < 2.0 and _PS_CACHE["value"]:
        return _PS_CACHE["value"]
    rows = []
    ps = _run(["ps", "-Ao", "pid=,rss=,pcpu=,comm="])
    for line in ps.splitlines():
        parts = line.strip().split(None, 3)
        if len(parts) < 4:
            continue
        pid, rss, cpu, comm = parts
        try:
            rows.append({"pid": int(pid), "rss": int(rss) * 1024,
                         "cpu": float(cpu), "comm": Path(comm).name})
        except ValueError:
            continue
    rows.sort(key=lambda r: r["rss"], reverse=True)
    out = rows[:limit]
    _PS_CACHE.update({"at": now, "value": out})
    return out


def resources() -> dict:
    now = time.monotonic()
    if now - _RES_CACHE["at"] < _RES_TTL and _RES_CACHE["value"]:
        return _RES_CACHE["value"]
    disk = shutil.disk_usage("/")
    val = {
        "cpu": _cpu_stats(),
        "mem": _mem_stats(),
        "gpu": _gpu_stats(),
        "procs": _top_procs(),
        "disk": {"total": disk.total, "used": disk.used, "free": disk.free},
        "cores": os.cpu_count(),
        "ts": time.time(),
    }
    _RES_CACHE.update({"at": now, "value": val})
    return val


# ── asset library ────────────────────────────────────────────────────────
def glb_info(path: Path) -> dict:
    """Parse the GLB JSON chunk for geometry/material facts (no deps)."""
    try:
        with open(path, "rb") as f:
            magic, _ver, _len = struct.unpack("<III", f.read(12))
            if magic != 0x46546C67:  # 'glTF'
                return {}
            clen, _ctype = struct.unpack("<II", f.read(8))
            js = json.loads(f.read(clen).decode("utf-8", "replace"))
        verts = tris = 0
        for mesh in js.get("meshes", []):
            for prim in mesh.get("primitives", []):
                pos = prim.get("attributes", {}).get("POSITION")
                if pos is not None:
                    verts += js["accessors"][pos].get("count", 0)
                idx = prim.get("indices")
                if idx is not None:
                    tris += js["accessors"][idx].get("count", 0) // 3
        return {
            "vertices": verts, "triangles": tris,
            "materials": len(js.get("materials", [])),
            "textures": len(js.get("textures", [])),
            "images": len(js.get("images", [])),
            "nodes": len(js.get("nodes", [])),
        }
    except Exception:
        return {}


def _entry(path: Path, url_base: str) -> dict | None:
    try:
        st = path.stat()
    except OSError:
        return None
    kind = "3d" if path.suffix.lower() in {".glb", ".gltf"} else \
           "image" if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} else "other"
    e = {
        "name": path.name, "kind": kind, "bytes": st.st_size,
        "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)),
        "mtime_ts": st.st_mtime,
        "url": f"{url_base}/{path.name}" if kind in ("image",) else None,
        "path": str(path),
    }
    if kind == "3d":
        e.update(glb_info(path))
    return e


ASSET_DIRS = [
    ("room", VR, "/vr"),
    ("3d", COMFY / "output" / "3d", "/files/out3d"),
    ("images", HOME / ".hermes" / "cache" / "generated" / "images", "/files/images"),
]


def scan_assets() -> list[dict]:
    out = []
    for group, d, url in ASSET_DIRS:
        if not d.is_dir():
            continue
        for p in d.iterdir():
            if p.name.startswith(".") or p.is_dir():
                continue
            e = _entry(p, url)
            if e:
                e["group"] = group
                out.append(e)
    out.sort(key=lambda e: e["mtime_ts"], reverse=True)
    return out


app = FastAPI(title="media-stack")


@app.get("/api/status")
def api_status():
    return {
        "services": stack_status(),
        "models": {
            "comfy": {"checkpoints": comfy_checkpoints(), "loras": comfy_loras()},
            "audio": [
                {"kind": k, "id": i, "label": l, "note": n, "cached": hf_cached(i)}
                for k, i, l, n in AUDIO_MODELS
            ],
        },
    }


@app.get("/api/resources")
def api_resources():
    return resources()


@app.get("/api/endpoints")
def api_endpoints():
    """Copy-paste URLs for pointing other local programs/pages at the stack."""
    hosts = ["127.0.0.1"]
    lan = lan_ip()
    if lan and lan not in hosts:
        hosts.append(lan)
    out = []
    for e in ENDPOINTS:
        url = f"http://{{host}}:{e['port']}{e['path']}"
        out.append({**e, "url": url, "origin": f"http://{{host}}:{e['port']}",
                    "status": "loaded" if e["svc"] == "panel" else None})
    return {"hosts": hosts, "lan_ip": lan, "panel_port": 8787, "items": out}


@app.get("/api/logs/{name}")
def api_logs(name: str, lines: int = 60):
    if name not in SERVICES:
        return JSONResponse({"error": "unknown service"}, status_code=404)
    return {"name": name, "text": tail(name, lines)}


@app.post("/api/start/{name}")
def api_start(name: str):
    if name not in SERVICES:
        return JSONResponse({"error": "unknown service"}, status_code=404)
    return start(name)


@app.post("/api/stop/{name}")
def api_stop(name: str):
    if name not in SERVICES:
        return JSONResponse({"error": "unknown service"}, status_code=404)
    return stop(name)


@app.post("/api/restart/{name}")
def api_restart(name: str):
    if name not in SERVICES:
        return JSONResponse({"error": "unknown service"}, status_code=404)
    stop(name)
    time.sleep(0.5)
    return start(name)


@app.post("/api/comfy/free")
def api_comfy_free():
    import urllib.request
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8188/free",
            data=json.dumps({"unload_models": True, "free_memory": True}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=10).read()
        return {"ok": True, "message": "ComfyUI VRAM released"}
    except Exception as exc:
        return {"ok": False, "message": f"free failed: {exc}"}


@app.post("/api/stop-all")
def api_stop_all():
    return {n: stop(n) for n in SERVICES}


@app.get("/api/vr/asset")
def api_vr_asset():
    """The GLB the room will open (current.json), falling back to pig.glb."""
    cur = api_vr_current()
    name = cur.get("name") or "pig.glb"
    p = VR / name
    if not p.exists():
        p = VR / "pig.glb"
        name = "pig.glb"
    if not p.exists():
        return {"present": False}
    st = p.stat()
    return {"present": True, "bytes": st.st_size, "name": name, "asset": cur.get("asset", "pig"),
            "src": f"/vr/{name}", "joints_file": f"joints_{_rig_slug(cur.get('asset', 'pig'))}.json",
            "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))}


@app.get("/api/assets")
def api_assets():
    return {"assets": scan_assets()}


# ── rig joints: hand-picked anatomy beats any bbox heuristic ─────────────
RIG = Path.home() / "media-stack" / "rig"


def _rig_slug(asset: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", (asset or "pig")).strip("-").lower()
    return slug[:60] or "pig"


def _rig_file(asset: str) -> Path:
    return RIG / f"joints_{_rig_slug(asset)}.json"


@app.get("/api/rig/assets")
def api_rig_assets():
    """Which assets already have a joint set saved."""
    RIG.mkdir(parents=True, exist_ok=True)
    out = []
    for p in sorted(RIG.glob("joints_*.json")):
        try:
            n = len(json.loads(p.read_text()))
        except Exception:
            n = 0
        out.append({"asset": p.stem.replace("joints_", ""), "joints": n})
    return {"assets": out}


@app.get("/api/rig/joints")
def api_rig_get(asset: str = "pig"):
    p = _rig_file(asset)
    if not p.exists():
        return {"joints": {}, "asset": _rig_slug(asset)}
    try:
        return {"joints": json.loads(p.read_text()), "asset": _rig_slug(asset)}
    except Exception as exc:
        return JSONResponse({"ok": False, "message": str(exc)}, status_code=500)


@app.post("/api/rig/joints")
def api_rig_save(payload: dict = Body(...)):
    asset = payload.get("asset", "pig")
    joints = payload.get("joints", {})
    p = _rig_file(asset)
    RIG.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(joints, indent=1))
    return {"ok": True, "saved": len(joints), "asset": _rig_slug(asset), "path": str(p)}


@app.post("/api/rig/build")
def api_rig_build(payload: dict = Body(default={})):
    """Rebuild a rigged GLB from the saved joints, in the background."""
    asset = payload.get("asset", "pig")
    jf = _rig_file(asset)
    if not jf.exists():
        return JSONResponse({"ok": False, "message": "no joints saved yet"}, status_code=400)

    def _resolve(p):
        """Relative paths are relative to the stack root, not the panel's cwd."""
        q = Path(p)
        return q if q.is_absolute() else (Path.home() / "media-stack" / q)

    src = _resolve(payload.get("source") or (VR / "hog_trellis2.glb"))
    dst = _resolve(payload.get("dest") or (VR / "hog_rigged.glb"))
    if not src.is_file():
        return JSONResponse({"ok": False, "message": f"missing {src}"}, status_code=400)
    RIG.mkdir(parents=True, exist_ok=True)
    log = RIG / f"build_{_rig_slug(asset)}.log"
    blender = Path.home() / "media-stack" / "bin" / "blender"
    cmd = [str(blender), "-b", "--python",
           str(Path.home() / "media-stack" / "scratch" / "rig_from_joints.py"),
           "--", str(src), str(dst), str(jf)]
    scale = payload.get("scale_to")
    if scale:
        cmd += ["--scale-to", str(scale)]
    with open(log, "wb") as fh:
        proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT,
                                start_new_session=True)
    return {"ok": True, "pid": proc.pid, "log": str(log), "dest": str(dst),
            "asset": _rig_slug(asset)}


@app.get("/api/rig/build/status")
def api_rig_build_status(asset: str = "pig"):
    log = RIG / f"build_{_rig_slug(asset)}.log"
    txt = log.read_text(errors="replace")[-4000:] if log.exists() else ""
    running = "Traceback" not in txt and "done:" not in txt and bool(txt)
    return {"log": txt, "likely_running": running, "asset": _rig_slug(asset)}


@app.get("/api/rig/templates")
def api_rig_templates():
    """The joint templates the picker and the auto-placer share (names must agree)."""
    sys.path.insert(0, str(STACK / "tools" / "rig"))
    try:
        import auto_joints as aj
        return {"templates": {k: [{"name": n, "prompt": d, "side": s} for n, d, s in v]
                              for k, v in aj.TEMPLATES.items()}}
    except Exception as exc:
        return JSONResponse({"ok": False, "message": str(exc)}, status_code=500)


@app.post("/api/rig/auto")
def api_rig_auto(payload: dict = Body(default={})):
    """Let the local VLM place the joints: renders views, asks Qwen3-VL, snaps to the mesh.

    Starts the vision server if it is down (first load is ~20 s) and runs the tool in the
    background; the room polls /api/rig/auto/status for the log."""
    asset = payload.get("asset") or "asset"
    src = payload.get("source")
    if not src:
        return JSONResponse({"ok": False, "message": "need source (path to the GLB)"}, status_code=400)
    template = payload.get("template") or "auto"
    py = STACK / "tools" / ".venv" / "bin" / "python"
    tool = STACK / "tools" / "rig" / "auto_joints.py"
    if not tool.is_file():
        return JSONResponse({"ok": False, "message": f"missing {tool}"}, status_code=500)
    started = None
    if not port_open(8082):
        started = start("vision")
    RIG.mkdir(parents=True, exist_ok=True)
    log = RIG / f"auto_{_rig_slug(asset)}.log"
    cmd = [str(py), str(tool), str(src), "--asset", asset, "--template", template]
    with open(log, "wb") as fh:
        proc = subprocess.Popen(cmd, cwd=str(STACK), stdout=fh, stderr=subprocess.STDOUT,
                                start_new_session=True)
    return {"ok": True, "pid": proc.pid, "log": str(log), "asset": _rig_slug(asset),
            "vision": (started or {}).get("message", "already running")}


@app.get("/api/rig/auto/status")
def api_rig_auto_status(asset: str = "asset"):
    log = RIG / f"auto_{_rig_slug(asset)}.log"
    txt = log.read_text(errors="replace")[-4000:] if log.exists() else ""
    done = "[auto] wrote" in txt or "Traceback" in txt or "VLM not reachable" in txt
    return {"log": txt, "done": done, "failed": ("Traceback" in txt or "VLM not reachable" in txt),
            "asset": _rig_slug(asset)}


@app.get("/api/vr/current")
def api_vr_current():
    """Which GLB the room opens by default when no ?src= is given."""
    f = VR / "current.json"
    if f.exists():
        try:
            return json.loads(f.read_text())
        except Exception:
            pass
    return {"src": "/vr/pig.glb", "asset": "pig", "name": "pig.glb"}


@app.post("/api/assets/use")
def api_assets_use(path: str):
    """Copy a GLB into the room under its own name and make it the default asset.

    It used to copy everything to `vr/pig.glb`, which is why a human loaded here came
    back as `pig.glb` and the joint picker then opened the pig's joint set."""
    src = Path(path)
    if not src.is_file() or src.suffix.lower() not in {".glb", ".gltf"}:
        return JSONResponse({"ok": False, "message": "not a GLB"}, status_code=400)
    slug = _rig_slug(src.stem.replace("_rigged", ""))
    dest = VR / f"{slug}{src.suffix.lower()}"
    try:
        if src.resolve() != dest.resolve():
            shutil.copy(src, dest)
        (VR / "current.json").write_text(json.dumps(
            {"src": f"/vr/{dest.name}", "asset": slug, "name": dest.name}, indent=1))
    except Exception as exc:
        return {"ok": False, "message": f"copy failed: {exc}"}
    return {"ok": True, "src": f"/vr/{dest.name}", "asset": slug,
            "message": f"room now uses {dest.name} (asset '{slug}')"}


@app.get("/api/comfy/job")
def api_comfy_job():
    """What ComfyUI is working on right now.

    The machine is shared — Dylan drives ComfyUI from its own UI, other agents
    queue jobs, and two heavy models at once will OOM. Surface occupancy instead
    of letting everyone guess.
    """
    import urllib.request as _u
    try:
        with _u.urlopen("http://127.0.0.1:8188/queue", timeout=3) as r:
            q = json.loads(r.read() or b"{}")
    except Exception as exc:
        return {"reachable": False, "error": str(exc)}

    running = q.get("queue_running") or []
    pending = q.get("queue_pending") or []
    out = {"reachable": True, "running": len(running), "pending": len(pending), "job": None}
    if running:
        item = running[0]
        graph = item[2] if len(item) > 2 and isinstance(item[2], dict) else {}
        types = sorted({v.get("class_type") for v in graph.values() if isinstance(v, dict)})
        prefix = ""
        for node in graph.values():
            if isinstance(node, dict):
                ins = node.get("inputs", {})
                if "filename_prefix" in ins:
                    prefix = str(ins["filename_prefix"])
        out["job"] = {"prompt_id": item[1], "nodes": len(graph),
                      "prefix": prefix, "kinds": types[:8],
                      "pipeline": next((t for t in ("Trellis2TextureStage", "Hunyuan3Dv2Conditioning",
                                                    "Hunyuan3Dv2ConditioningMultiView", "KSampler")
                                        if t in types), types[0] if types else "")}
    return out


app.mount("/vr", StaticFiles(directory=str(VR), html=True), name="vr")
for _mount, _dir in (("/files/out3d", COMFY / "output" / "3d"),
                     ("/files/images", HOME / ".hermes" / "cache" / "generated" / "images"),
                     ("/files/output", STACK / "output"),
                     ("/files/comfy_output", COMFY / "output"),
                     ("/files/scratch", STACK / "scratch"),
                     ("/files/train", STACK / "train" / "datasets"),
                     ("/files/game", STACK / "game"),
                     ("/brand", Path(__file__).parent / "brand")):
    # Create on first boot: a missing directory makes StaticFiles raise at import time.
    _dir.mkdir(parents=True, exist_ok=True)
    app.mount(_mount, StaticFiles(directory=str(_dir)), name=_mount.strip("/").replace("/", "_"))


import sys as _sys
_sys.path.insert(0, str(Path(__file__).parent))
import studio as _studio  # noqa: E402  (Studio tabs: run forms, progress, galleries, inventory)
app.include_router(_studio.router)
STUDIO_HTML = Path(__file__).parent / "studio.html"


@app.get("/", response_class=HTMLResponse)
def index():
    # Re-read each request so edits to studio.html show on reload without a restart.
    return STUDIO_HTML.read_text()




# (legacy four-tab page removed 2026-11-01; the Studio page is the only UI)


if __name__ == "__main__":
    import uvicorn
    # PANEL_HOST=0.0.0.0 exposes the panel to the LAN so the Windows/VR box can
    # load the room over HTTP instead of copying files. Loopback by default.
    host = os.environ.get("PANEL_HOST", "127.0.0.1")
    uvicorn.run(app, host=host, port=8787, log_level="warning")