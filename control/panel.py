#!/usr/bin/env python3
"""Local media-stack control panel — one origin, three tabs.

  Services   start/stop the local services and see installed models
  VR Room    the WebXR asset test room (served from /vr/)
  Resources  live CPU / GPU / memory / swap / disk, and per-process RSS

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
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

HOME = Path.home()
STACK = HOME / "media-stack"
LOGS = STACK / "logs"
RUN = STACK / "run"
COMFY = STACK / "ComfyUI"
VR = STACK / "vr"
AUDIO_PY = STACK / "audio" / ".venv" / "bin" / "python"

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
}


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


def start(name: str) -> dict:
    svc = SERVICES[name]
    if read_pid(name) or port_open(svc["port"]):
        return {"ok": True, "already": True, "message": f"{svc['label']} already running"}
    log = LOGS / f"{name}.log"
    fh = open(log, "ab")
    fh.write(f"\n=== start {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n".encode())
    fh.flush()
    proc = subprocess.Popen(
        svc["cmd"], cwd=svc["cwd"], stdout=fh, stderr=subprocess.STDOUT,
        env=_base_env(), start_new_session=True,
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
    p = VR / "pig.glb"
    if not p.exists():
        return {"present": False}
    st = p.stat()
    return {"present": True, "bytes": st.st_size,
            "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))}


@app.get("/api/assets")
def api_assets():
    return {"assets": scan_assets()}


@app.post("/api/assets/use")
def api_assets_use(path: str):
    """Copy any GLB into the room as pig.glb so the VR tab picks it up."""
    src = Path(path)
    if not src.is_file() or src.suffix.lower() not in {".glb", ".gltf"}:
        return JSONResponse({"ok": False, "message": "not a GLB"}, status_code=400)
    try:
        shutil.copy(src, VR / "pig.glb")
    except Exception as exc:
        return {"ok": False, "message": f"copy failed: {exc}"}
    return {"ok": True, "message": f"room now uses {src.name}"}


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
                     ("/files/images", HOME / ".hermes" / "cache" / "generated" / "images")):
    # Create on first boot: a missing directory makes StaticFiles raise at import time.
    _dir.mkdir(parents=True, exist_ok=True)
    app.mount(_mount, StaticFiles(directory=str(_dir)), name=_mount.strip("/").replace("/", "_"))


@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE


PAGE = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>media stack</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  :root{color-scheme:dark}
  *{box-sizing:border-box}
  body{margin:0;font:14px/1.5 ui-sans-serif,-apple-system,system-ui,sans-serif;
       background:#0b0d10;color:#e6e8eb}
  header{padding:20px 28px 0}
  h1{font-size:17px;font-weight:600;margin:0}
  .sub{color:#8b929c;font-size:12px;margin-top:2px}
  nav{display:flex;gap:4px;padding:14px 28px 0;border-bottom:1px solid #1c2027}
  nav button{background:none;border:none;border-bottom:2px solid transparent;color:#8b929c;
             padding:8px 14px;font-size:13px;cursor:pointer;font-family:inherit;border-radius:0}
  nav button:hover{color:#e6e8eb}
  nav button.active{color:#e6e8eb;border-bottom-color:#1f6feb}
  main{padding:22px 28px 40px}
  .tab{display:none}
  .tab.active{display:block}
  .grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(330px,1fr))}
  .card{background:#14171c;border:1px solid #232830;border-radius:10px;padding:16px}
  .row{display:flex;align-items:center;justify-content:space-between;gap:10px}
  .name{font-weight:600;font-size:15px}
  .desc{color:#8b929c;font-size:12px;margin-top:2px}
  .dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:6px}
  .on{background:#37d67a;box-shadow:0 0 8px #37d67a88}
  .off{background:#4a5160}
  .warn{background:#f5a623;box-shadow:0 0 8px #f5a62388}
  button{background:#1d2229;color:#e6e8eb;border:1px solid #2c323c;border-radius:7px;
         padding:6px 11px;font-size:12px;cursor:pointer;font-family:inherit}
  button:hover{background:#262d36;border-color:#3a424f}
  button.primary{background:#1f6feb;border-color:#1f6feb}
  button.danger:hover{background:#3a1d21;border-color:#7a2c35}
  .btns{display:flex;gap:7px;margin-top:14px;flex-wrap:wrap}
  .meta{font-size:11px;color:#6f7681;font-variant-numeric:tabular-nums;margin-top:10px}
  pre{background:#0b0d10;border:1px solid #232830;border-radius:8px;padding:10px;
      font-size:11px;line-height:1.45;max-height:180px;overflow:auto;white-space:pre-wrap;
      color:#9aa2ad;margin:12px 0 0}
  h2{font-size:12px;text-transform:uppercase;letter-spacing:.07em;color:#8b929c;
     margin:24px 0 10px;font-weight:600}
  li{list-style:none;display:flex;justify-content:space-between;gap:10px;padding:6px 0;
     border-bottom:1px solid #1c2027;font-size:13px}
  ul{margin:0;padding:0}
  .tag{font-size:10px;padding:1px 6px;border-radius:4px;border:1px solid #2c323c;color:#8b929c}
  .cached{color:#37d67a;border-color:#265c3d}
  code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}
  /* resources */
  .stats{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(200px,1fr))}
  .stat .k{font-size:11px;text-transform:uppercase;letter-spacing:.07em;color:#8b929c}
  .stat .v{font-size:26px;font-weight:600;font-variant-numeric:tabular-nums;margin:2px 0 0}
  .stat .v small{font-size:13px;color:#8b929c;font-weight:400}
  .bar{height:6px;background:#1c2027;border-radius:4px;overflow:hidden;margin-top:10px}
  .bar>i{display:block;height:100%;background:#1f6feb;transition:width .3s}
  .bar.g>i{background:#37d67a}
  .bar.a>i{background:#f5a623}
  .bar.r>i{background:#e05561}
  table{width:100%;border-collapse:collapse;font-size:12px;font-variant-numeric:tabular-nums}
  th{text-align:left;color:#8b929c;font-weight:500;font-size:11px;text-transform:uppercase;
     letter-spacing:.06em;padding:6px 0;border-bottom:1px solid #232830}
  td{padding:5px 0;border-bottom:1px solid #16191f}
  td.r{text-align:right}
  .vrwrap{border:1px solid #232830;border-radius:10px;overflow:hidden;background:#0b0d10}
  iframe{width:100%;height:min(72vh,760px);border:0;display:block}
  /* assets */
  .agrid{display:grid;gap:14px;grid-template-columns:repeat(auto-fill,minmax(240px,1fr))}
  .asset{background:#14171c;border:1px solid #232830;border-radius:10px;overflow:hidden;
         display:flex;flex-direction:column}
  .asset .thumb{height:150px;background:#0b0d10;display:flex;align-items:center;
                justify-content:center;overflow:hidden;position:relative}
  .asset .thumb img{width:100%;height:100%;object-fit:contain}
  .asset .thumb .ph{font-size:30px;color:#39414d}
  .asset .body{padding:10px 12px;display:flex;flex-direction:column;gap:5px;flex:1}
  .asset .fn{font-size:12px;word-break:break-all;line-height:1.35}
  .asset .kv{font-size:11px;color:#7f8791;font-variant-numeric:tabular-nums}
  .asset .acts{display:flex;gap:5px;margin-top:auto;padding-top:8px;flex-wrap:wrap}
  .asset .acts button{padding:4px 8px;font-size:11px}
  .pill{position:absolute;top:8px;left:8px;font-size:10px;padding:2px 7px;border-radius:5px;
        background:#000a;border:1px solid #2c323c;color:#9aa2ad}
  .pill.tex{color:#37d67a;border-color:#265c3d}
</style></head><body>
<header>
  <h1>media stack</h1>
  <div class="sub">local generation &middot; M3 Max 64 GB &middot; nothing leaves the machine</div>
</header>
<nav>
  <button data-tab="services" class="active">Services</button>
  <button data-tab="vr">VR Room</button>
  <button data-tab="assets">Assets</button>
  <button data-tab="resources">Resources</button>
</nav>
<main>
  <section class="tab active" id="tab-services">
    <div class="card" id="occupancy" style="margin-bottom:14px"><span class="desc">checking GPU occupancy…</span></div>
    <div class="grid" id="services"></div>
    <h2>ComfyUI models</h2>
    <div class="card"><ul id="comfy-models"><li><span>loading…</span></li></ul>
      <div class="btns"><button onclick="act('comfy/free')">Free VRAM</button></div></div>
    <h2>Audio models (mlx-audio)</h2>
    <div class="card"><ul id="audio-models"><li><span>loading…</span></li></ul></div>
  </section>

  <section class="tab" id="tab-vr">
    <div class="row" style="margin-bottom:12px">
      <div>
        <div class="name">Asset test room</div>
        <div class="desc" id="vr-asset">checking asset…</div>
      </div>
      <div class="btns" style="margin:0">
        <button class="primary" onclick="window.open('/vr/index.html','_blank')">Open full screen</button>
        <button onclick="location.reload()">Reload room</button>
      </div>
    </div>
    <div class="vrwrap"><iframe id="vrframe" src="/vr/index.html"
      allow="xr-spatial-tracking; fullscreen; gyroscope; accelerometer"></iframe></div>
    <div class="meta">WebXR needs Chrome or Edge. For actual VR, use “Open full screen” —
      iframe mode is for desktop inspection only.</div>
  </section>

  <section class="tab" id="tab-assets">
    <div class="row" style="margin-bottom:14px">
      <div>
        <div class="name">Assets</div>
        <div class="desc">everything generated or staged — 3D meshes, reference images, room files</div>
      </div>
      <div class="btns" style="margin:0">
        <button onclick="setFilter('all')" data-f="all" class="primary">All</button>
        <button onclick="setFilter('3d')" data-f="3d">3D</button>
        <button onclick="setFilter('image')" data-f="image">Images</button>
        <button onclick="refreshAssets()">Refresh</button>
      </div>
    </div>
    <div class="agrid" id="assets"><div class="desc">loading…</div></div>
  </section>

  <section class="tab" id="tab-resources">
    <div class="stats" id="stats"></div>

    <h2>Top processes by memory</h2>
    <div class="card"><table id="procs">
      <thead><tr><th>process</th><th class="r">pid</th><th class="r">rss</th><th class="r">cpu%</th></tr></thead>
      <tbody></tbody></table></div>

    <h2>Disk</h2>
    <div class="card"><div class="row"><div class="desc">root volume</div>
      <div class="meta" id="disk" style="margin:0"></div></div>
      <div class="bar"><i id="diskbar"></i></div></div>
  </section>
</main>

<script>
const $ = (id) => document.getElementById(id);
const GB = 1024**3, MB = 1024**2;

function flash(msg){
  const d=document.createElement('div');
  d.textContent=msg;
  d.style.cssText='position:fixed;bottom:18px;left:50%;transform:translateX(-50%);background:#1d2229;border:1px solid #2c323c;padding:8px 14px;border-radius:8px;font-size:12px;z-index:9';
  document.body.appendChild(d); setTimeout(()=>d.remove(),2200);
}

async function act(path){
  const r = await fetch('/api/'+path,{method:'POST'});
  const j = await r.json();
  if(j.message) flash(j.message);
  setTimeout(refreshServices, 400);
}

// ── tabs ──────────────────────────────────────────────────────────────
let current = 'services';
document.querySelectorAll('nav button').forEach(b=>{
  b.onclick = () => {
    current = b.dataset.tab;
    document.querySelectorAll('nav button').forEach(x=>x.classList.toggle('active', x===b));
    document.querySelectorAll('.tab').forEach(s=>s.classList.toggle('active', s.id==='tab-'+current));
    if (current==='resources') refreshResources();
    if (current==='assets') refreshAssets();
  };
});

// ── assets ────────────────────────────────────────────────────────────
let assetFilter = 'all';
let assetCache = [];
let assetView = [];

function setFilter(f){
  assetFilter = f;
  document.querySelectorAll('[data-f]').forEach(b=>b.classList.toggle('primary', b.dataset.f===f));
  renderAssets();
}

function fmtBytes(b){
  return b > GB ? (b/GB).toFixed(2)+' GB' : b > MB ? (b/MB).toFixed(1)+' MB' : (b/1024).toFixed(0)+' KB';
}

function renderAssets(){
  const list = assetCache.filter(a=> assetFilter==='all' || a.kind===assetFilter);
  assetView = list;
  if(!list.length){ $('assets').innerHTML = '<div class="desc">nothing here yet</div>'; return; }
  $('assets').innerHTML = list.map((a,i)=>{
    const is3d = a.kind==='3d';
    const thumb = a.url
      ? `<img src="${a.url}" loading="lazy" alt="${a.name}">`
      : `<div class="ph">${is3d?'◈':'▤'}</div>`;
    let kv = `${fmtBytes(a.bytes)} · ${a.mtime}`;
    if(is3d && a.triangles!==undefined){
      kv = `${(a.triangles||0).toLocaleString()} tris · ${fmtBytes(a.bytes)}`;
    }
    const tex = is3d && (a.textures||a.images)
      ? `<span class="pill tex">textured</span>`
      : (is3d ? `<span class="pill">untextured</span>` : '');
    return `<div class="asset">
      <div class="thumb">${thumb}${tex}</div>
      <div class="body">
        <div class="fn">${a.name}</div>
        <div class="kv">${kv}</div>
        ${is3d?`<div class="kv">${a.materials||0} material(s) · ${a.nodes||0} node(s)</div>`:''}
        <div class="acts">
          ${is3d?`<button class="primary" onclick="useAssetIdx(${i})">Set in room</button>`:''}
          ${a.url?`<button onclick="window.open('${a.url}','_blank')">Open</button>`:''}
        </div>
      </div></div>`;
  }).join('');
}

async function refreshAssets(){
  const r = await (await fetch('/api/assets')).json();
  assetCache = r.assets || [];
  renderAssets();
}

async function useAssetIdx(i){
  const a = assetView[i];
  if(!a) return;
  await useAsset(a.path);
}

async function useAsset(path){
  const res = await fetch('/api/assets/use?path=' + encodeURIComponent(path), {method:'POST'});
  const j = await res.json();
  flash(j.message || 'done');
  refreshVr();
  const f = $('vrframe'); if(f) f.src = '/vr/index.html?t=' + Date.now();
}

// ── GPU occupancy (shared machine: who is using ComfyUI right now) ─────
async function refreshOccupancy(){
  const el = $('occupancy');
  try{
    const j = await (await fetch('/api/comfy/job')).json();
    if(!j.reachable){
      el.innerHTML = '<span class="dot off"></span><b>ComfyUI unreachable</b>' +
        '<div class="meta">not running — nothing is using the GPU from this stack</div>';
      return;
    }
    if(!j.job){
      el.innerHTML = '<span class="dot on"></span><b>GPU idle</b>' +
        `<div class="meta">queue empty${j.pending?' · '+j.pending+' pending':''}</div>`;
      return;
    }
    const k = j.job;
    el.innerHTML = `<span class="dot warn"></span><b>ComfyUI busy — ${k.pipeline||'job'}</b>
      <div class="meta">${k.nodes} nodes &middot; output <code>${k.prefix||'?'}</code>
      &middot; ${j.pending} pending &middot; <code>${k.prompt_id.slice(0,8)}</code></div>
      <div class="meta">a second heavy job now risks OOM on 64 GB — generation scripts wait for the queue</div>`;
  }catch(e){ el.innerHTML = '<span class="desc">occupancy unavailable</span>'; }
}

// ── services ──────────────────────────────────────────────────────────
async function refreshServices(){
  refreshOccupancy();
  const s = await (await fetch('/api/status')).json();
  $('services').innerHTML = Object.entries(s.services).map(([key,v])=>{
    const cls = v.responding ? 'on' : (v.running ? 'warn' : 'off');
    const state = v.responding ? 'running' : (v.running ? 'starting' : 'stopped');
    return `<div class="card">
      <div class="row">
        <div><div class="name">${v.label}</div><div class="desc">${v.desc}</div></div>
        <div style="font-size:12px;color:#9aa2ad"><span class="dot ${cls}"></span>${state}</div>
      </div>
      <div class="meta">port ${v.port}${v.pid?` &middot; pid ${v.pid}`:''}</div>
      <div class="btns">
        <button class="primary" onclick="act('start/${key}')">Start</button>
        <button onclick="act('restart/${key}')">Restart</button>
        <button class="danger" onclick="act('stop/${key}')">Stop</button>
        <button onclick="showLog('${key}')">Log</button>
      </div>
      <pre id="log-${key}" style="display:none"></pre>
    </div>`;
  }).join('');

  $('comfy-models').innerHTML = s.models.comfy.checkpoints.length
    ? s.models.comfy.checkpoints.map(c=>`<li><code>${c}</code></li>`).join('')
    : '<li><span style="color:#8b929c">no checkpoints installed</span></li>';

  $('audio-models').innerHTML = s.models.audio.map(m=>`<li><div><code>${m.label}</code>
      <div style="color:#6f7681;font-size:11px">${m.note}</div></div>
      <span class="tag ${m.cached?'cached':''}">${m.cached?'downloaded':'on demand'}</span></li>`).join('');
}

async function showLog(name){
  const pre=$('log-'+name);
  const j=await (await fetch('/api/logs/'+name+'?lines=60')).json();
  pre.textContent=j.text||'(empty)';
  pre.style.display = pre.style.display==='none' ? 'block':'none';
}

// ── resources ─────────────────────────────────────────────────────────
function bar(pct, tone){
  const v = Math.max(0, Math.min(100, pct));
  const t = tone || (v>88?'r':v>70?'a':v>40?'':'g');
  return `<div class="bar ${t}"><i style="width:${v}%"></i></div>`;
}

async function refreshResources(){
  const r = await (await fetch('/api/resources')).json();
  const c = r.cpu||{}, m = r.mem||{}, g = r.gpu||{}, d = r.disk||{};

  const memPct = m.total ? (m.used/m.total*100) : 0;
  const swapPct = m.swap_total ? (m.swap_used/m.swap_total*100) : 0;
  const diskPct = d.total ? (d.used/d.total*100) : 0;

  const gpuTxt = g.available && g.util!==undefined ? `${g.util}<small>%</small>` : '<small>n/a</small>';
  const gpuBar = g.available && g.util!==undefined ? bar(g.util) : '<div class="bar"><i style="width:0"></i></div>';

  $('stats').innerHTML = `
    <div class="card stat"><div class="k">CPU</div>
      <div class="v">${c.busy!==undefined?c.busy:'–'}<small>%</small></div>
      ${bar(c.busy||0)}
      <div class="meta">${r.cores} cores &middot; load ${(c.load||[]).map(x=>x.toFixed(2)).join(' / ')||'–'}</div>
    </div>
    <div class="card stat"><div class="k">GPU</div>
      <div class="v">${gpuTxt}</div>${gpuBar}
      <div class="meta">${g.available?`renderer ${g.renderer??'–'}% &middot; tiler ${g.tiler??'–'}%`:'not exposed'}</div>
    </div>
    <div class="card stat"><div class="k">Memory</div>
      <div class="v">${(m.used/GB).toFixed(1)}<small> / ${(m.total/GB).toFixed(0)} GB</small></div>
      ${bar(memPct)}
      <div class="meta">wired ${(m.wired/GB).toFixed(1)} GB &middot; compressed ${(m.compressed/GB).toFixed(1)} GB</div>
    </div>
    <div class="card stat"><div class="k">Swap</div>
      <div class="v">${(m.swap_used/MB).toFixed(0)}<small> / ${(m.swap_total/MB).toFixed(0)} MB</small></div>
      ${bar(swapPct,'a')}
      <div class="meta">${swapPct>50?'pressure — models may be evicting':'healthy'}</div>
    </div>`;

  $('procs').querySelector('tbody').innerHTML = (r.procs||[]).map(p=>`<tr>
      <td><code>${p.comm}</code></td>
      <td class="r">${p.pid}</td>
      <td class="r">${p.rss>GB?(p.rss/GB).toFixed(2)+' GB':(p.rss/MB).toFixed(0)+' MB'}</td>
      <td class="r">${p.cpu.toFixed(1)}</td></tr>`).join('');

  $('disk').textContent = `${(d.used/GB).toFixed(0)} / ${(d.total/GB).toFixed(0)} GB used · ${(d.free/GB).toFixed(0)} GB free`;
  $('diskbar').style.width = diskPct+'%';
}

// ── vr asset line ─────────────────────────────────────────────────────
async function refreshVr(){
  const a = await (await fetch('/api/vr/asset')).json();
  $('vr-asset').textContent = a.present
    ? `pig.glb · ${(a.bytes/MB).toFixed(1)} MB · updated ${a.mtime}`
    : 'pig.glb not present yet — drop it in ~/media-stack/vr/';
}

refreshServices(); refreshVr(); refreshAssets();
setInterval(()=>{ if(current==='services') refreshServices(); }, 2500);
setInterval(()=>{ if(current==='resources') refreshResources(); }, 2000);
</script></body></html>
"""

if __name__ == "__main__":
    import uvicorn
    # PANEL_HOST=0.0.0.0 exposes the panel to the LAN so the Windows/VR box can
    # load the room over HTTP instead of copying files. Loopback by default.
    host = os.environ.get("PANEL_HOST", "127.0.0.1")
    uvicorn.run(app, host=host, port=8787, log_level="warning")
