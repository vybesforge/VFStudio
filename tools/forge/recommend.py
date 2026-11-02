#!/usr/bin/env python3
"""forge-recommend — probe this machine and name the VF Studio models to fetch.

Reads models/manifest.json (`fit` on each ComfyUI file, `hf_models` for the MLX
repos the installer already documents). Never downloads and never calls a cloud API.

  bin/forge-recommend                         # human report
  bin/forge-recommend --json                  # machine + tiers
  bin/forge-recommend --ids                   # ids for the recommended set
  bin/forge-recommend --ids --tier essentials
  fetch-models --profile auto                 # fetch essentials + quality
  fetch-models $(bin/forge-recommend --ids)

The live probe is the product. --fixture substitutes a synthetic capability
profile (nvidia-16gb, apple-24gb, amd-8gb, …) and is for tests, not a catalog
of computers.

Tiers
  essentials   smallest useful set. At 64 GB unified this matches install.sh.
  quality      daily models that fit. `fetch-models --profile auto` includes these.
  optional     heavy or alternate. `fetch-models --profile full` adds them.

Fitting
  Discrete NVIDIA (CUDA) and AMD (ROCm): the largest card's VRAM, never the sum.
  A 0.75 GB slack covers nvidia-smi reporting ~16376 MiB on a card sold as 16 GB,
  so min_vram_gb 16 still matches and min_vram_gb 20 does not.
  Apple Silicon: unified RAM, MLX for voice / vision / writer. fp8 is not the
  edit path (it upcasts to bf16). MLX repos are not fetched for CUDA or ROCm.
  CPU: classical upscalers only.
  Disk: keep 10 GB free under the stack root. Essentials are placed first, then
  the smallest quality pipelines that still fit, then optional.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

# nvidia-smi reports 16376 MiB on a card sold as 16 GB. Thresholds are nominal.
VRAM_SLACK_GB = 0.75
DISK_HEADROOM_GB = 10.0
TIER_ORDER = ("essentials", "quality", "optional")
TIER_RANK = {"essentials": 0, "quality": 1, "optional": 2, "skip": 3}
TIER_SETS = {
    "essentials": {"essentials"},
    "recommended": {"essentials", "quality"},
    "quality": {"essentials", "quality"},
    "optional": {"optional"},
    "all": {"essentials", "quality", "optional"},
}

# Synthetic capability profiles for tests. Not a list of supported computers.
# A normal run probes the machine in front of it.
FIXTURES: dict[str, dict] = {
    "nvidia-32gb": {
        "label": "32 GB NVIDIA plus a 6 GB second card",
        "os": "linux", "arch": "x86_64", "os_pretty": "Linux",
        "cpu": "x86_64 CPU", "cpu_cores": 16,
        "ram_gb": 128, "disk_free_gb": 2000, "disk_path": "~/media-stack",
        "apple_silicon": False, "gpu_class": "nvidia",
        "gpus": [
            {"index": 0, "name": "NVIDIA 32 GB", "vram_gb": 32, "vendor": "nvidia", "driver": "550"},
            {"index": 1, "name": "NVIDIA 6 GB", "vram_gb": 6, "vendor": "nvidia", "driver": "550"},
        ],
    },
    "nvidia-16gb": {
        "label": "16 GB NVIDIA (driver reports 16376 MiB) on Windows",
        "os": "windows", "arch": "x86_64", "os_pretty": "Windows",
        "cpu": "x86_64 CPU", "cpu_cores": 16,
        "ram_gb": 64, "disk_free_gb": 800, "disk_path": "C:/media-stack",
        "apple_silicon": False, "gpu_class": "nvidia",
        "gpus": [
            {"index": 0, "name": "NVIDIA 16 GB", "vram_gb": round(16376 / 1024, 3),
             "vendor": "nvidia", "driver": "560"},
        ],
    },
    "nvidia-10gb": {
        "label": "10 GB NVIDIA",
        "os": "linux", "arch": "x86_64", "os_pretty": "Linux",
        "cpu": "x86_64 CPU", "cpu_cores": 8,
        "ram_gb": 32, "disk_free_gb": 500, "disk_path": "~/media-stack",
        "apple_silicon": False, "gpu_class": "nvidia",
        "gpus": [{"index": 0, "name": "NVIDIA 10 GB", "vram_gb": 10, "vendor": "nvidia", "driver": "550"}],
    },
    "nvidia-4gb": {
        "label": "4 GB NVIDIA",
        "os": "linux", "arch": "x86_64", "os_pretty": "Linux",
        "cpu": "x86_64 CPU", "cpu_cores": 4,
        "ram_gb": 16, "disk_free_gb": 80, "disk_path": "~/media-stack",
        "apple_silicon": False, "gpu_class": "nvidia",
        "gpus": [{"index": 0, "name": "NVIDIA 4 GB", "vram_gb": 4, "vendor": "nvidia", "driver": "550"}],
    },
    "amd-8gb": {
        "label": "8 GB AMD",
        "os": "linux", "arch": "x86_64", "os_pretty": "Linux",
        "cpu": "x86_64 CPU", "cpu_cores": 8,
        "ram_gb": 32, "disk_free_gb": 400, "disk_path": "~/media-stack",
        "apple_silicon": False, "gpu_class": "amd",
        "gpus": [{"index": 0, "name": "AMD 8 GB", "vram_gb": 8, "vendor": "amd", "driver": "amdgpu"}],
    },
    "apple-64gb": {
        "label": "64 GB Apple unified memory",
        "os": "darwin", "arch": "arm64", "os_pretty": "macOS",
        "cpu": "Apple Silicon", "cpu_cores": 16,
        "ram_gb": 64, "disk_free_gb": 400, "disk_path": "~/media-stack",
        "apple_silicon": True, "gpu_class": "apple",
        "gpus": [{"index": 0, "name": "Apple Silicon", "vram_gb": None, "vendor": "apple", "driver": "Metal"}],
    },
    "apple-32gb": {
        "label": "32 GB Apple unified memory",
        "os": "darwin", "arch": "arm64", "os_pretty": "macOS",
        "cpu": "Apple Silicon", "cpu_cores": 10,
        "ram_gb": 32, "disk_free_gb": 200, "disk_path": "~/media-stack",
        "apple_silicon": True, "gpu_class": "apple",
        "gpus": [{"index": 0, "name": "Apple Silicon", "vram_gb": None, "vendor": "apple", "driver": "Metal"}],
    },
    "apple-24gb": {
        "label": "24 GB Apple unified memory",
        "os": "darwin", "arch": "arm64", "os_pretty": "macOS",
        "cpu": "Apple Silicon", "cpu_cores": 8,
        "ram_gb": 24, "disk_free_gb": 200, "disk_path": "~/media-stack",
        "apple_silicon": True, "gpu_class": "apple",
        "gpus": [{"index": 0, "name": "Apple Silicon", "vram_gb": None, "vendor": "apple", "driver": "Metal"}],
    },
    "apple-disk-22gb": {
        "label": "64 GB Apple unified memory with 22 GB free disk",
        "os": "darwin", "arch": "arm64", "os_pretty": "macOS",
        "cpu": "Apple Silicon", "cpu_cores": 16,
        "ram_gb": 64, "disk_free_gb": 22, "disk_path": "~/media-stack",
        "apple_silicon": True, "gpu_class": "apple",
        "gpus": [{"index": 0, "name": "Apple Silicon", "vram_gb": None, "vendor": "apple", "driver": "Metal"}],
    },
    "cpu": {
        "label": "no GPU",
        "os": "linux", "arch": "x86_64", "os_pretty": "Linux",
        "cpu": "virtual CPU", "cpu_cores": 2,
        "ram_gb": 16, "disk_free_gb": 100, "disk_path": "~/media-stack",
        "apple_silicon": False, "gpu_class": "cpu",
        "gpus": [],
    },
}


def stack_root() -> Path:
    env = os.environ.get("MEDIA_STACK")
    if env:
        return Path(env).expanduser()
    here = Path(__file__).resolve().parents[2]
    if (here / "models" / "manifest.json").is_file():
        return here
    return Path.home() / "media-stack"


def load_manifest(path: Path | None = None) -> dict:
    path = path or (stack_root() / "models" / "manifest.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("models", [])
    data.setdefault("hf_models", [])
    return data


def _run(cmd: list[str], timeout: float = 4.0) -> str:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout or ""


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def parse_nvidia_smi(text: str) -> list[dict]:
    """Parse `nvidia-smi --query-gpu=index,name,memory.total,driver_version --format=csv,noheader,nounits`."""
    gpus = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        index_s, mem_s, driver = parts[0], parts[-2], parts[-1]
        name = ", ".join(parts[1:-2]).strip()
        try:
            index = int(index_s)
        except ValueError:
            index = len(gpus)
        mem_digits = re.sub(r"[^0-9.]", "", mem_s)
        vram = None
        if mem_digits:
            mib = float(mem_digits)
            if mib > 0:
                vram = round(mib / 1024, 3)
        gpus.append({
            "index": index, "name": name or "NVIDIA GPU", "vram_gb": vram,
            "vendor": "nvidia", "driver": driver or None,
        })
    return gpus


def _cpu_name(os_name: str) -> str:
    if os_name == "linux":
        for line in _read(Path("/proc/cpuinfo")).splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    elif os_name == "darwin":
        name = _run(["sysctl", "-n", "machdep.cpu.brand_string"]).strip()
        if name:
            return name
    elif os_name == "windows":
        name = os.environ.get("PROCESSOR_IDENTIFIER", "").strip()
        if name:
            return name
    proc = platform.processor().strip()
    return proc or platform.machine()


def _ram_gb(os_name: str) -> float:
    if os_name == "linux":
        for line in _read(Path("/proc/meminfo")).splitlines():
            if line.startswith("MemTotal:"):
                kb = float(line.split()[1])
                return kb / (1024 ** 2)
    elif os_name == "darwin":
        raw = _run(["sysctl", "-n", "hw.memsize"]).strip()
        if raw.isdigit():
            return int(raw) / (1024 ** 3)
    elif os_name == "windows":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(stat)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return stat.ullTotalPhys / (1024 ** 3)
        except (OSError, AttributeError, ValueError):
            return 0.0
    return 0.0


def _os_pretty(os_name: str) -> str:
    if os_name == "linux":
        for line in _read(Path("/etc/os-release")).splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip().strip('"')
        return "Linux"
    if os_name == "darwin":
        ver = _run(["sw_vers", "-productVersion"]).strip()
        return f"macOS {ver}".strip()
    if os_name == "windows":
        return platform.platform()
    return os_name


def _linux_drm_gpus() -> list[dict]:
    root = Path("/sys/class/drm")
    if not root.is_dir():
        return []
    vendors = {"0x10de": "nvidia", "0x1002": "amd", "0x8086": "intel"}
    gpus = []
    for card in sorted(root.iterdir()):
        if not re.fullmatch(r"card\d+", card.name):
            continue
        dev = card / "device"
        vendor = vendors.get(_read(dev / "vendor").strip().lower())
        if not vendor:
            continue
        raw = _read(dev / "mem_info_vram_total").strip()
        vram = None
        if raw.isdigit() and int(raw) > 0:
            vram = round(int(raw) / (1024 ** 3), 3)
        name = _read(dev / "product_name").strip() or {"nvidia": "NVIDIA GPU", "amd": "AMD GPU", "intel": "Intel GPU"}[vendor]
        gpus.append({"index": len(gpus), "name": name, "vram_gb": vram, "vendor": vendor, "driver": None})
    return gpus


def _windows_gpus() -> list[dict]:
    script = (
        "Get-CimInstance Win32_VideoController | "
        "Select-Object Name,AdapterRAM,DriverVersion | ConvertTo-Json -Compress"
    )
    raw = _run(["powershell", "-NoProfile", "-Command", script], timeout=8)
    if not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    rows = data if isinstance(data, list) else [data]
    gpus = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("Name") or "GPU")
        low = name.lower()
        if "nvidia" in low:
            vendor = "nvidia"
        elif "amd" in low or "radeon" in low:
            vendor = "amd"
        elif "intel" in low:
            vendor = "intel"
        elif "apple" in low:
            vendor = "apple"
        else:
            vendor = "unknown"
        vram = None
        ram = row.get("AdapterRAM")
        try:
            ram_i = int(ram)
        except (TypeError, ValueError):
            ram_i = 0
        # AdapterRAM is a signed 32-bit field and saturates at 4 GB. Ignore that lie.
        if 0 < ram_i < (2 ** 31 - 1) and not (ram_i >= 2 ** 31 - 4096 and vendor in ("nvidia", "amd")):
            if ram_i > 256 * 1024 ** 2:
                vram = round(ram_i / (1024 ** 3), 3)
        gpus.append({
            "index": len(gpus), "name": name, "vram_gb": vram, "vendor": vendor,
            "driver": (str(row.get("DriverVersion")) if row.get("DriverVersion") else None),
        })
    return gpus


def is_apple_silicon(os_name: str, arch: str, cpu: str) -> bool:
    if os_name != "darwin":
        return False
    if arch.lower() in ("arm64", "aarch64"):
        return True
    return "apple" in cpu.lower()


def classify(os_name: str, arch: str, cpu: str, gpus: list[dict]) -> str:
    """Pick the compute class recommendations follow. Discrete NVIDIA/AMD wins over the SoC."""
    for vendor in ("nvidia", "amd"):
        if any(g.get("vendor") == vendor for g in gpus):
            return vendor
    if is_apple_silicon(os_name, arch, cpu):
        return "apple"
    return "cpu"


def best_vram_gb(gpus: list[dict]) -> float:
    vals = [float(g["vram_gb"]) for g in gpus if g.get("vendor") in ("nvidia", "amd") and g.get("vram_gb")]
    return max(vals) if vals else 0.0


def normalize(machine: dict) -> dict:
    m = copy.deepcopy(machine)
    m["gpus"] = list(m.get("gpus") or [])
    m["best_vram_gb"] = round(best_vram_gb(m["gpus"]), 3)
    m["ram_gb"] = float(m.get("ram_gb") or 0)
    m["disk_free_gb"] = float(m.get("disk_free_gb") or 0)
    m["notes"] = list(m.get("notes") or [])
    m.setdefault("os", "linux")
    m.setdefault("arch", "")
    m.setdefault("cpu", "")
    m.setdefault("cpu_cores", os.cpu_count() or 0)
    m.setdefault("os_pretty", "")
    m.setdefault("disk_path", "")
    m.setdefault("apple_silicon", False)
    m.setdefault("gpu_class", "cpu")
    m.setdefault("fixture", None)
    m.setdefault("label", None)
    return m


def _disk(path: Path) -> tuple[float, str, str | None]:
    probe = path
    walked = None
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    if not probe.exists():
        probe = Path.home()
        walked = str(probe)
    usage = shutil.disk_usage(probe)
    note = None
    if walked or probe.resolve() != path.resolve():
        if not path.exists():
            note = f"stack root {path} is not on disk yet; free space is for {probe}"
    return usage.free / (1024 ** 3), str(path), note


_PROBE_CACHE: dict = {"t": 0.0, "key": None, "machine": None}


def _probe_key(stack: Path) -> str:
    """Changes when the manifest or the visible GPUs change, so a stale probe is not reused."""
    man = stack / "models" / "manifest.json"
    try:
        mtime = str(man.stat().st_mtime_ns)
    except OSError:
        mtime = "0"
    smi = _run([
        "nvidia-smi", "--query-gpu=index,name,memory.total",
        "--format=csv,noheader,nounits",
    ], timeout=2.0).strip()
    flags = f"{os.environ.get('VF_GPU', '')}|{os.environ.get('VF_UNCENSORED', '')}"
    return f"{stack}|{mtime}|{smi}|{flags}"


def probe(stack: Path | None = None, *, ttl: float = 20.0) -> dict:
    stack = (stack or stack_root()).expanduser()
    key = _probe_key(stack)
    now = time.monotonic()
    if _PROBE_CACHE["key"] == key and _PROBE_CACHE["machine"] and now - _PROBE_CACHE["t"] < ttl:
        return copy.deepcopy(_PROBE_CACHE["machine"])
    machine = _probe_uncached(stack)
    _PROBE_CACHE.update({"t": now, "key": key, "machine": machine})
    return copy.deepcopy(machine)


def _probe_uncached(stack: Path) -> dict:
    system = platform.system()
    os_name = {"Linux": "linux", "Darwin": "darwin", "Windows": "windows"}.get(system, system.lower())
    arch = platform.machine()
    cpu = _cpu_name(os_name)
    notes: list[str] = []
    gpus = parse_nvidia_smi(_run([
        "nvidia-smi", "--query-gpu=index,name,memory.total,driver_version",
        "--format=csv,noheader,nounits",
    ]))
    if not gpus and os_name == "windows":
        gpus = _windows_gpus()
        if any(g["vendor"] in ("nvidia", "amd") and not g["vram_gb"] for g in gpus):
            notes.append("GPU name came from Win32_VideoController without a trustworthy VRAM figure. Install the NVIDIA driver so nvidia-smi works before fetching large models.")
    if not any(g["vendor"] in ("nvidia", "amd") for g in gpus) and os_name == "linux":
        drm = [g for g in _linux_drm_gpus() if g["vendor"] != "nvidia" or not gpus]
        # Keep nvidia-smi results; sysfs only fills AMD/Intel (and NVIDIA if smi failed).
        if gpus:
            drm = [g for g in drm if g["vendor"] != "nvidia"]
        gpus.extend(drm)
    apple = is_apple_silicon(os_name, arch, cpu)
    if apple and not any(g["vendor"] == "apple" for g in gpus):
        gpus.append({
            "index": len(gpus), "name": cpu if "Apple" in cpu else "Apple Silicon",
            "vram_gb": None, "vendor": "apple", "driver": "Metal",
        })
    gpu_class = classify(os_name, arch, cpu, gpus)
    if gpu_class == "cpu" and any(g["vendor"] == "intel" for g in gpus):
        notes.append("Intel graphics are not a generation path in this stack.")
    if gpu_class == "cpu" and not gpus:
        notes.append("No NVIDIA, AMD, or Apple GPU found.")
    disk_gb, disk_path, disk_note = _disk(stack)
    if disk_note:
        notes.append(disk_note)
    return normalize({
        "os": os_name,
        "arch": arch,
        "os_pretty": _os_pretty(os_name),
        "cpu": cpu,
        "cpu_cores": os.cpu_count() or 0,
        "ram_gb": _ram_gb(os_name),
        "disk_free_gb": disk_gb,
        "disk_path": disk_path,
        "gpus": gpus,
        "gpu_class": gpu_class,
        "apple_silicon": apple,
        "notes": notes,
        "fixture": None,
        "source": "probe",
    })


def fixture_machine(name: str) -> dict:
    if name not in FIXTURES:
        known = ", ".join(FIXTURES)
        raise SystemExit(f"unknown fixture {name!r} (known: {known})")
    data = copy.deepcopy(FIXTURES[name])
    label = data.pop("label", name)
    data["fixture"] = name
    data["label"] = label
    data["source"] = "fixture"
    data.setdefault("notes", [])
    return normalize(data)


def _fits_number(have: float, need: float, *, slack: float) -> bool:
    return have + slack + 1e-9 >= need


def _head_fits(model: dict, machine: dict) -> tuple[bool, str]:
    fit = model.get("fit") or {}
    if not fit:
        return False, "no fit metadata; left out of every profile until it is classified"
    cls = machine["gpu_class"]
    backends = fit.get("backends") or ["nvidia", "amd", "apple"]
    if cls not in backends:
        if cls == "cpu":
            return False, "no GPU detected — this model is not a CPU path"
        return False, fit.get("skip_note") or f"no {cls} path (built for {', '.join(backends)})"
    if cls == "apple":
        need = float(fit.get("min_unified_gb") or 0)
        have = float(machine["ram_gb"])
        if not _fits_number(have, need, slack=0):
            return False, f"needs {need:g} GB unified memory (detected {have:.0f} GB)"
    elif cls in ("nvidia", "amd"):
        need = float(fit.get("min_vram_gb") or 0)
        have = float(machine["best_vram_gb"])
        if not _fits_number(have, need, slack=VRAM_SLACK_GB):
            shown = f"{have:.1f}".rstrip("0").rstrip(".")
            return False, f"needs {need:g} GB VRAM on one card (largest is {shown} GB)"
    elif not fit.get("cpu_ok"):
        return False, "no GPU detected — this model is not a CPU path"
    return True, fit.get("note") or "fits"


def _pipeline_ids(model: dict) -> list[str]:
    return [model["id"]] + list((model.get("fit") or {}).get("includes") or [])


def _gb(by_id: dict, ids: set[str] | list[str]) -> float:
    return sum(float(by_id[i]["gb"]) for i in ids if i in by_id)


class _Choice:
    def __init__(self, model: dict, bucket: str, reason: str):
        self.model = model
        self.bucket = bucket
        self.reason = reason

    @property
    def id(self) -> str:
        return self.model["id"]


def _disk_budget(free_gb: float) -> tuple[float, float]:
    """Return (budget_gb, headroom_gb). Below 11 GB free, hold back 1 GB instead of 10."""
    if free_gb <= 0:
        return 0.0, 0.0
    if free_gb < DISK_HEADROOM_GB + 1:
        hold = 1.0 if free_gb > 1 else 0.0
        return max(0.0, free_gb - hold), hold
    return free_gb - DISK_HEADROOM_GB, DISK_HEADROOM_GB


def recommend(manifest: dict, machine: dict) -> dict:
    machine = normalize(machine)
    models = manifest.get("models") or []
    by_id = {m["id"]: m for m in models}
    heads = [m for m in models if not (m.get("fit") or {}).get("companion")]
    notes = list(machine.get("notes") or [])

    chosen: list[_Choice] = []
    skipped: list[_Choice] = []
    for model in heads:
        ok, reason = _head_fits(model, machine)
        tier = (model.get("fit") or {}).get("tier") or "optional"
        if tier not in TIER_RANK:
            tier = "optional"
        if ok:
            chosen.append(_Choice(model, tier, reason))
        else:
            skipped.append(_Choice(model, "skip", reason))

    # When several edit/etc. heads fit, keep the one this GPU class prefers.
    by_alt: dict[str, list[_Choice]] = {}
    for c in chosen:
        alt = (c.model.get("fit") or {}).get("alt")
        if alt:
            by_alt.setdefault(alt, []).append(c)
    cls = machine["gpu_class"]
    for alt, group in by_alt.items():
        if len(group) < 2:
            continue

        def rank(c: _Choice) -> tuple:
            pr = ((c.model.get("fit") or {}).get("alt_priority") or {}).get(cls, 0)
            return (pr, -float(c.model["gb"]), c.id)

        winner = max(group, key=rank)
        for c in group:
            if c is winner:
                continue
            chosen.remove(c)
            skipped.append(_Choice(
                c.model, "skip",
                f"covered by {winner.id} on this {cls} box",
            ))

    def drop_unmet_requires() -> None:
        changed = True
        while changed:
            changed = False
            have = {c.id for c in chosen}
            for c in list(chosen):
                reqs = (c.model.get("fit") or {}).get("requires") or []
                missing = [r for r in reqs if r not in have]
                if not missing:
                    continue
                why = []
                for r in missing:
                    host = next((s for s in skipped if s.id == r), None)
                    why.append(f"{r} ({host.reason})" if host else r)
                chosen.remove(c)
                skipped.append(_Choice(c.model, "skip", "needs " + "; ".join(why)))
                changed = True

    drop_unmet_requires()

    image_ess = [c for c in chosen if c.bucket == "essentials" and (c.model.get("fit") or {}).get("task") == "image"]
    if not image_ess:
        cands = [c for c in chosen if c.bucket == "quality" and (c.model.get("fit") or {}).get("task") == "image"]
        if cands:
            pick = min(cands, key=lambda c: (float(c.model["gb"]), c.id))
            pick.bucket = "essentials"
            pick.reason = "promoted to essentials: smallest image model that fits this GPU. " + pick.reason

    disk_free = float(machine["disk_free_gb"])
    disk_checked = disk_free > 0
    budget, headroom = _disk_budget(disk_free) if disk_checked else (10 ** 9, 0.0)
    if not disk_checked:
        notes.append("disk free could not be read; sizes were not checked against free space")

    def selected_ids(picks: list[_Choice]) -> set[str]:
        ids: set[str] = set()
        for c in picks:
            ids.update(_pipeline_ids(c.model))
        return ids

    def freed(picks: list[_Choice], victim: _Choice) -> float:
        victim_ids = set(_pipeline_ids(victim.model))
        others: set[str] = set()
        for c in picks:
            if c is victim:
                continue
            others.update(_pipeline_ids(c.model))
        return _gb(by_id, victim_ids - others)

    def incremental(picks: list[_Choice], cand: _Choice) -> float:
        have = selected_ids(picks)
        extra = [i for i in _pipeline_ids(cand.model) if i not in have]
        return _gb(by_id, extra)

    disk_skipped: list[_Choice] = []
    if not disk_checked:
        picked = list(chosen)
    else:
        picked = [c for c in chosen if c.bucket == "essentials"]
        while picked and _gb(by_id, selected_ids(picked)) > budget + 0.05:
            victim = max(picked, key=lambda c: (freed(picked, c), c.id))
            size = freed(picked, victim)
            before = _gb(by_id, selected_ids(picked))
            picked.remove(victim)
            after = _gb(by_id, selected_ids(picked))
            disk_skipped.append(_Choice(
                victim.model, "skip",
                f"disk: {size:.1f} GB pipeline does not fit in "
                f"{disk_free:.0f} GB free under {machine.get('disk_path') or 'the stack root'} "
                f"({headroom:.0f} GB held back)",
            ))
            if after >= before - 0.001:
                break
        for bucket in ("quality", "optional"):
            pool = [c for c in chosen if c.bucket == bucket]
            pool.sort(key=lambda c: (incremental(picked, c), c.id))
            for cand in pool:
                reqs = (cand.model.get("fit") or {}).get("requires") or []
                have = selected_ids(picked)
                if any(r not in have for r in reqs):
                    disk_skipped.append(_Choice(
                        cand.model, "skip",
                        "needs " + ", ".join(r for r in reqs if r not in have) + ", dropped for disk",
                    ))
                    continue
                extra = incremental(picked, cand)
                if _gb(by_id, have) + extra <= budget + 0.05:
                    picked.append(cand)
                else:
                    disk_skipped.append(_Choice(
                        cand.model, "skip",
                        f"disk: {extra:.1f} GB more does not fit in {disk_free:.0f} GB free "
                        f"under {machine.get('disk_path') or 'the stack root'} ({headroom:.0f} GB held back)",
                    ))

    picked_ids = {c.id for c in picked}
    final_skipped = [s for s in skipped if s.id not in picked_ids]
    final_skipped.extend(s for s in disk_skipped if s.id not in picked_ids)
    # A head that fit VRAM but lost the disk pack should not also keep its old "fits" row.
    skip_by_id = {}
    for s in final_skipped:
        skip_by_id[s.id] = s

    status: dict[str, tuple[str, str]] = {}
    for model in models:
        status[model["id"]] = ("skip", "not selected")
    for s in skip_by_id.values():
        status[s.id] = ("skip", s.reason)
    for c in picked:
        status[c.id] = (c.bucket, c.reason)
        for inc in (c.model.get("fit") or {}).get("includes") or []:
            if inc not in status:
                continue
            prev_b, _prev_r = status[inc]
            if TIER_RANK[c.bucket] < TIER_RANK.get(prev_b, 3):
                status[inc] = (c.bucket, f"included with {c.id}")
    for s in skip_by_id.values():
        for inc in (s.model.get("fit") or {}).get("includes") or []:
            if inc not in status:
                continue
            if status[inc][0] == "skip" and status[inc][1] == "not selected":
                status[inc] = ("skip", f"included with {s.id}: {s.reason}")

    flat = []
    for model in models:
        bucket, reason = status.get(model["id"], ("skip", "not selected"))
        fit = model.get("fit") or {}
        flat.append({
            "id": model["id"],
            "bucket": bucket,
            "gb": model.get("gb"),
            "task": fit.get("task"),
            "tier": fit.get("tier"),
            "role": model.get("role"),
            "path": model.get("path"),
            "reason": reason,
            "companion": bool(fit.get("companion")),
            "includes": list(fit.get("includes") or []),
            "gate": fit.get("gate") or "open",
            "license": fit.get("license") or "",
        })

    hf_rows = _recommend_hf(manifest.get("hf_models") or [], machine, _gb(by_id, {i for i, (b, _) in status.items() if b != "skip"}), budget if disk_checked else 10 ** 9, disk_checked)
    if any(m["bucket"] == "skip" and str(m["reason"]).startswith("disk:") for m in flat):
        notes.append(
            f"Free space under {machine.get('disk_path') or 'the stack root'} is {disk_free:.0f} GB. "
            f"Held back {headroom:.0f} GB. Models that fit the GPU but not the disk are in the skip list."
        )
    notes.extend(_advice(machine))

    present = _presence(flat)
    for row in flat:
        row["present"] = present.get(row["id"], False)

    summary = _summary(machine, flat, hf_rows, headroom if disk_checked else 0)
    return {
        "machine": _machine_out(machine),
        "models": flat,
        "tiers": {b: [m for m in flat if m["bucket"] == b] for b in ("essentials", "quality", "optional", "skip")},
        "hf": hf_rows,
        "notes": notes,
        "disk": {
            "free_gb": round(disk_free, 1),
            "path": machine.get("disk_path") or "",
            "headroom_gb": headroom if disk_checked else 0,
            "recommended_gb": round(sum(m["gb"] for m in flat if m["bucket"] in ("essentials", "quality")), 1),
            "optional_gb": round(sum(m["gb"] for m in flat if m["bucket"] == "optional"), 1),
            "essentials_gb": round(sum(m["gb"] for m in flat if m["bucket"] == "essentials"), 1),
            "checked": disk_checked,
        },
        "summary": summary,
        "fetch": {
            "ids": ids_for({"models": flat}, "recommended"),
            "command": "fetch-models --profile auto",
        },
        "engines": engines(machine),
    }


def _recommend_hf(rows: list[dict], machine: dict, used_gb: float, budget: float, disk_checked: bool) -> dict:
    cls = machine["gpu_class"]
    out = {b: [] for b in ("essentials", "quality", "optional", "skip")}
    pending: list[tuple[str, dict, str]] = []
    for row in rows:
        backends = row.get("backends") or ["apple"]
        if cls not in backends:
            out["skip"].append({**_hf_public(row), "bucket": "skip", "reason": row.get("other_os") or f"no {cls} path"})
            continue
        if row.get("opt_in") and not machine.get("uncensored"):
            out["skip"].append({
                **_hf_public(row), "bucket": "skip",
                "reason": "opt-in uncensored model — rerun with --uncensored or VF_UNCENSORED=1",
            })
            continue
        if row.get("min_vram_gb") and cls in ("nvidia", "amd"):
            need = float(row["min_vram_gb"])
            if not _fits_number(float(machine["best_vram_gb"]), need, slack=VRAM_SLACK_GB):
                out["skip"].append({
                    **_hf_public(row), "bucket": "skip",
                    "reason": f"needs {need:g} GB VRAM on one card (largest is {float(machine['best_vram_gb']):.0f} GB)",
                })
                continue
        if cls == "apple":
            need = float(row.get("min_unified_gb") or 0)
            if not _fits_number(float(machine["ram_gb"]), need, slack=0):
                out["skip"].append({
                    **_hf_public(row), "bucket": "skip",
                    "reason": f"needs {need:g} GB unified memory (detected {float(machine['ram_gb']):.0f} GB)",
                })
                continue
        tier = row.get("tier") or "optional"
        pending.append((tier, row, row.get("note") or "fits"))
    running = used_gb
    for tier in TIER_ORDER:
        group = [item for item in pending if item[0] == tier]
        group.sort(key=lambda item: (float(item[1].get("gb") or 0), item[1]["id"]))
        for tier_name, row, reason in group:
            gb = float(row.get("gb") or 0)
            if disk_checked and running + gb > budget + 0.05:
                out["skip"].append({
                    **_hf_public(row), "bucket": "skip",
                    "reason": f"disk: {gb:g} GB MLX repo does not fit in the space left under the stack root",
                })
            else:
                running += gb
                out[tier_name].append({**_hf_public(row), "bucket": tier_name, "reason": reason})
    return out


def _hf_public(row: dict) -> dict:
    return {
        "id": row["id"], "repo": row.get("repo"), "gb": row.get("gb"), "task": row.get("task"),
        "role": row.get("role"), "uncensored": bool(row.get("uncensored")),
        "gate": row.get("gate") or "open", "license": row.get("license") or "",
        "opt_in": bool(row.get("opt_in")), "fetch": row.get("fetch", True),
    }


def _advice(machine: dict) -> list[str]:
    cls = machine["gpu_class"]
    best = float(machine["best_vram_gb"])
    notes = []
    discrete = [g for g in machine["gpus"] if g.get("vendor") in ("nvidia", "amd") and g.get("vram_gb")]
    small = [g for g in discrete if float(g["vram_gb"]) < 8]
    big = [g for g in discrete if float(g["vram_gb"]) >= 8]
    if small and big:
        small_txt = ", ".join(f"{g['name']} ({g['vram_gb']:g} GB)" for g in small)
        big_g = max(big, key=lambda g: float(g["vram_gb"]))
        notes.append(
            f"{small_txt} cannot run the diffusion models in this manifest. "
            f"Fitting uses {big_g['name']} ({big_g['vram_gb']:g} GB) only — one model is not split across cards."
        )
    if machine.get("apple_silicon") and cls in ("nvidia", "amd"):
        notes.append("Apple Silicon is also present. ComfyUI recommendations follow the discrete GPU. MLX weights are not fetched for it.")
    if cls == "apple":
        if float(machine["ram_gb"]) >= 48:
            notes.append("Apple Silicon: MLX is the voice, vision, and writer path. fp8 ComfyUI files upcast to bf16 — the edit path is the Q4 GGUF, and Flux dev is the slow image model.")
        else:
            notes.append("Under 48 GB unified: skip Flux dev and the 27B writer. Run Qwen-Image-Edit on its own (stack free first).")
    elif cls in ("nvidia", "amd") and best >= 24:
        notes.append("A 27B Q4 writer is about 17 GB and must time-share this card (stack free first). On Linux/Windows that is a GGUF via llama-server, not the MLX repo. See INSTALL-UBUNTU.md §6.")
    elif cls in ("nvidia", "amd") and best > 0:
        notes.append("Under 24 GB VRAM, text encoders offload. Run one family at a time and stack free between them. Writer: a ≤14B Q4 GGUF (about 9 GB) via llama-server, not the 27B. See INSTALL-UBUNTU.md §6.")
    if cls == "amd":
        notes.append("AMD is probed, but this stack was measured on Apple Silicon and NVIDIA. Smoke-test klein before fetching the quality tier.")
    if cls == "cpu":
        notes.append("No usable GPU. Only the tiny classical upscalers are recommended; gen image / video need a GPU.")
    return notes


def _presence(flat: list[dict]) -> dict[str, bool]:
    root = stack_root() / "ComfyUI" / "models"
    out = {}
    for row in flat:
        path = row.get("path")
        out[row["id"]] = bool(path) and (root / path).is_file()
    return out


def _machine_out(machine: dict) -> dict:
    gpus = []
    for g in machine["gpus"]:
        gpus.append({
            "index": g.get("index"),
            "name": g.get("name"),
            "vram_gb": g.get("vram_gb"),
            "vendor": g.get("vendor"),
            "driver": g.get("driver"),
        })
    return {
        "os": machine.get("os"),
        "os_pretty": machine.get("os_pretty"),
        "arch": machine.get("arch"),
        "cpu": machine.get("cpu"),
        "cpu_cores": machine.get("cpu_cores"),
        "ram_gb": round(float(machine.get("ram_gb") or 0), 1),
        "disk_free_gb": round(float(machine.get("disk_free_gb") or 0), 1),
        "disk_path": machine.get("disk_path"),
        "gpus": gpus,
        "gpu_class": machine.get("gpu_class"),
        "apple_silicon": bool(machine.get("apple_silicon")),
        "best_vram_gb": machine.get("best_vram_gb"),
        "fixture": machine.get("fixture"),
        "label": machine.get("label"),
        "source": machine.get("source") or ("fixture" if machine.get("fixture") else "probe"),
    }


def _summary(machine: dict, flat: list[dict], hf: dict, headroom: float) -> dict:
    cls = machine["gpu_class"]
    if cls == "apple":
        headline = f"Apple Silicon · {float(machine['ram_gb']):.0f} GB unified"
    elif cls in ("nvidia", "amd"):
        best = float(machine["best_vram_gb"])
        name = ""
        discrete = [g for g in machine["gpus"] if g.get("vendor") == cls and g.get("vram_gb")]
        if discrete:
            name = max(discrete, key=lambda g: float(g["vram_gb"]))["name"]
        headline = f"{cls} · {best:.0f} GB on {name}".strip()
    else:
        headline = "no GPU"
    ids = [m["id"] for m in flat if m["bucket"] in ("essentials", "quality")]
    hf_ids = [m["id"] for b in ("essentials", "quality") for m in hf.get(b, [])]
    smoke = []
    if "flux2-klein-4b" in ids:
        smoke.append('gen image "a brass compass on an old map" --model klein --seed 1')
    elif "z-image-turbo" in ids:
        smoke.append('gen image "a brass compass on an old map" --seed 1')
    elif "realesrgan-x4plus" in ids:
        smoke.append("gen upscale in.png --method esrgan")
    if "kokoro-82m" in hf_ids:
        smoke.append('voice say "hello from the studio"')
    return {
        "headline": headline,
        "os": machine.get("os"),
        "gpu_class": cls,
        "ram_gb": round(float(machine.get("ram_gb") or 0), 1),
        "best_vram_gb": machine.get("best_vram_gb"),
        "disk_free_gb": round(float(machine.get("disk_free_gb") or 0), 1),
        "headroom_gb": headroom,
        "essentials_gb": round(sum(m["gb"] for m in flat if m["bucket"] == "essentials"), 1),
        "quality_gb": round(sum(m["gb"] for m in flat if m["bucket"] == "quality"), 1),
        "optional_gb": round(sum(m["gb"] for m in flat if m["bucket"] == "optional"), 1),
        "skip_n": sum(1 for m in flat if m["bucket"] == "skip"),
        "fetch_command": "fetch-models --profile auto",
        "smoke": smoke,
        "fixture": machine.get("fixture"),
    }


def ids_for(result: dict, tier: str) -> list[str]:
    if tier not in TIER_SETS:
        known = ", ".join(TIER_SETS)
        raise SystemExit(f"unknown tier {tier!r} (known: {known})")
    want = TIER_SETS[tier]
    return [m["id"] for m in result["models"] if m["bucket"] in want]


def _fmt_gb(value) -> str:
    if value is None:
        return "   –"
    return f"{float(value):6.2f}"


def render_text(result: dict) -> str:
    m = result["machine"]
    lines = ["VF Studio forge — what to fetch on this machine", ""]
    if m.get("fixture"):
        lines.append(f"fixture   {m['fixture']}  {m.get('label') or ''}".rstrip())
    lines.append("machine")
    lines.append(f"  os      {m.get('os')}  {m.get('arch')}  {m.get('os_pretty') or ''}".rstrip())
    cores = m.get("cpu_cores") or 0
    lines.append(f"  cpu     {m.get('cpu') or 'unknown'}   {cores} cores")
    lines.append(f"  ram     {m.get('ram_gb')} GB")
    lines.append(f"  disk    {m.get('disk_free_gb')} GB free under {m.get('disk_path')}")
    cls = m.get("gpu_class")
    if cls == "apple":
        budget = f"unified {m.get('ram_gb')} GB"
    elif cls in ("nvidia", "amd"):
        budget = f"{m.get('best_vram_gb')} GB VRAM on the largest card"
    else:
        budget = "no GPU"
    lines.append(f"  gpu     {cls}   fitting budget {budget}")
    eng = result.get("engines") or {}
    if eng:
        lines.append(f"  engine  {eng.get('backend')}   card {eng.get('gpu_index')} {eng.get('gpu_name') or ''}".rstrip())
    for g in m.get("gpus") or []:
        vram = f"{g['vram_gb']} GB" if g.get("vram_gb") else "unified"
        driver = f"driver {g['driver']}" if g.get("driver") else "driver n/a"
        lines.append(f"          [{g.get('index')}] {g.get('name')}   {vram}   {driver}")
    if result.get("notes"):
        lines.append("")
        lines.append("notes")
        for note in result["notes"]:
            lines.append(f"  - {note}")
    lines.append("")
    present = {row["id"]: row.get("present") for row in result["models"]}
    for bucket, blurb in (
        ("essentials", "fetch these first"),
        ("quality", "included in fetch-models --profile auto"),
        ("optional", "not in --profile auto; fetch-models --profile full"),
        ("skip", "do not fetch"),
    ):
        rows = [row for row in result["tiers"][bucket] if not row.get("companion")]
        total = sum(row["gb"] or 0 for row in result["tiers"][bucket])
        lines.append(f"{bucket:<12} {total:6.1f} GB   {blurb}")
        if not rows:
            lines.append("  (none)")
        for row in rows:
            mark = "✓" if present.get(row["id"]) else "·"
            extra = ""
            incs = [i for i in row.get("includes") or []]
            if incs:
                extra = "  + " + ", ".join(incs)
            lines.append(f"  {mark} {row['id']:<28} {_fmt_gb(row['gb'])} GB  {row['reason']}{extra}")
        lines.append("")
    hf = result.get("hf") or {}
    lines.append("mlx / hf   Apple Silicon repos (not fetch-models; HF_HUB_DISABLE_XET=1 hf download <repo>)")
    any_hf = False
    for bucket in ("essentials", "quality", "optional", "skip"):
        rows = hf.get(bucket) or []
        if not rows:
            continue
        any_hf = True
        lines.append(f"  {bucket}")
        for row in rows:
            repo = row.get("repo") or ""
            lines.append(f"    {row['id']:<28} {_fmt_gb(row['gb'])} GB  {repo}  {row['reason']}")
    if not any_hf:
        lines.append("  (none listed)")
    lines.append("")
    lines.append("next")
    lines.append("  fetch-models --profile auto")
    lines.append("  fetch-models $(bin/forge-recommend --ids)")
    if result["summary"].get("smoke"):
        lines.append("  stack start comfy")
        for cmd in result["summary"]["smoke"]:
            lines.append(f"  {cmd}")
    lines.append("")
    return "\n".join(lines)


def select_gpu(machine: dict, gpu_index: int | None = None) -> dict | None:
    """Largest discrete card, or the card VF_GPU / gpu_index names. Never sums VRAM."""
    gpus = list(machine.get("gpus") or [])
    if gpu_index is not None:
        for g in gpus:
            if g.get("index") == gpu_index:
                return g
        return None
    discrete = [g for g in gpus if g.get("vendor") in ("nvidia", "amd") and g.get("vram_gb")]
    if not discrete:
        return None
    return max(discrete, key=lambda g: float(g["vram_gb"]))


def engines(machine: dict, *, uncensored: bool | None = None, gpu_index: int | None = None) -> dict:
    """Which local engine each modality should use on this machine.

    CUDA and ROCm share ComfyUI. MLX stays on Apple Silicon. CPU is the fallback
    only where the tool can actually run (upscale, stems, print) — not for diffusion.
    """
    machine = normalize(machine)
    if uncensored is None:
        uncensored = bool(machine.get("uncensored"))
    if gpu_index is None and machine.get("gpu_index") is not None:
        gpu_index = machine.get("gpu_index")
    cls = machine["gpu_class"]
    backend = {"nvidia": "cuda", "amd": "rocm", "apple": "mlx", "cpu": "cpu"}.get(cls, "cpu")
    gpu = select_gpu(machine, gpu_index)
    comfy_device = "mps" if cls == "apple" else ("cpu" if cls == "cpu" else "cuda")
    vram = float(gpu["vram_gb"]) if gpu and gpu.get("vram_gb") else float(machine.get("best_vram_gb") or 0)
    diffusion = cls != "cpu"
    edit = "skip" if not diffusion else ("fp8" if backend in ("cuda", "rocm") and _fits_number(vram, 24, slack=VRAM_SLACK_GB) else "gguf")
    if cls == "apple":
        audio_engine, audio_note = "mlx-audio", "Kokoro / Parakeet / Qwen3-TTS through the MLX audio server."
        llm_engine = "mlx-lm"
        vlm_engine, vlm_model = "mlx-vlm", "mlx-community/Qwen3-VL-8B-Instruct-4bit"
        vlm_note = "Local vision through MLX."
        clone_note = "Voice clone through the MLX audio server."
    else:
        audio_engine, audio_note = "speaches", "Kokoro and faster-whisper through speaches. MLX weights are not loaded."
        llm_engine = "llama-server"
        vlm_engine, vlm_model = "llama-server", ""
        vlm_note = "Qwen3-VL GGUF plus its mmproj, via llama-server. Set VLM_GGUF and VLM_MMPROJ."
        clone_note = "No MLX clone here. Point VOICE_SERVER at a local PyTorch cloner if you run one."
    if cls == "apple":
        writer, writer_note = (
            "mlx-community/Qwen3.8-27B-Uncensored-OptiQ-4bit",
            "Labeled uncensored writer. This is the Apple default; the CUDA/ROCm build of the same choice is opt-in.",
        )
    elif uncensored:
        writer, writer_note = (
            os.environ.get("WRITER_GGUF") or "",
            "Labeled uncensored writer (opt-in). Point llama-server at a local GGUF with WRITER_GGUF. Not auto-downloaded.",
        )
    else:
        writer, writer_note = (
            os.environ.get("LLM_MODEL") or "",
            "Set LLM_MODEL to a local GGUF, or VF_UNCENSORED=1 for the labeled uncensored writer.",
        )
    stems_device = "mps" if cls == "apple" else ("cuda" if cls in ("nvidia", "amd") else "cpu")
    stems_note = {
        "apple": "Demucs on Metal.",
        "nvidia": "Demucs on CUDA.",
        "amd": "Demucs on ROCm (PyTorch still calls the device cuda).",
        "cpu": "Demucs on CPU. Slow, and it runs.",
    }[cls if cls in ("apple", "nvidia", "amd", "cpu") else "cpu"]

    def row(engine: str, note: str, runnable: bool, **extra: object) -> dict:
        out = {
            "engine": engine, "backend": backend, "device": extra.pop("device", comfy_device),
            "note": note, "runnable": runnable,
        }
        out.update(extra)
        return out

    heavy = diffusion and (cls == "apple" or _fits_number(vram, 12, slack=VRAM_SLACK_GB))
    return {
        "backend": backend,
        "gpu_index": None if gpu is None else gpu.get("index"),
        "gpu_name": None if gpu is None else gpu.get("name"),
        "uncensored": bool(uncensored),
        "image": row("comfy", "ComfyUI. Edit weights follow the card: fp8 on large CUDA/ROCm, GGUF otherwise." if diffusion else "No GPU — diffusion is not a CPU path. Upscalers still run.", diffusion, edit=edit),
        "video": row("comfy", "ComfyUI. Wan is the light clip; HunyuanVideo is the heavier one.", heavy),
        "sfx": row("comfy", "Sound effects through ComfyUI (Stable Audio).", diffusion),
        "music": row("comfy", "ACE-Step through ComfyUI. MiniMax via MLX is Apple-only.", diffusion),
        "tts": row(audio_engine, audio_note, cls == "apple" or backend in ("cuda", "rocm")),
        "stt": row(audio_engine, audio_note, cls == "apple" or backend in ("cuda", "rocm")),
        "clone": row("mlx-audio" if cls == "apple" else "pytorch", clone_note, cls == "apple"),
        "llm": row(llm_engine, writer_note, bool(writer) or cls != "cpu", model=writer),
        "vision": row(vlm_engine, vlm_note, cls == "apple" or backend in ("cuda", "rocm"), model=vlm_model),
        "stems": row("demucs", stems_note, True, device=stems_device),
        "3d": row("comfy", "TRELLIS.2 through ComfyUI, same device as image.", heavy),
        "print": row("cpu", "Mesh check and slice are CPU tools.", True, device="cpu"),
    }


def preflight(manifest: dict, ids: list[str] | None = None) -> dict:
    """Offline gate check. Does not download and does not print a token.

    gate hf-login blocks unless HF_TOKEN, HUGGING_FACE_HUB_TOKEN, or VF_SKIP_GATE is set.
    gate notice is a license reminder and does not block.
    """
    by = {m["id"]: m for m in manifest.get("models") or []}
    wanted = list(ids) if ids is not None else [m["id"] for m in manifest.get("models") or []]
    token = bool(os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN") or os.environ.get("VF_SKIP_GATE"))
    rows = []
    blocked = []
    for i in wanted:
        model = by.get(i)
        if not model:
            continue
        fit = model.get("fit") or {}
        gate = fit.get("gate") or "open"
        row = {"id": i, "gate": gate, "license": fit.get("license") or ""}
        rows.append(row)
        if gate == "hf-login" and not token:
            blocked.append(i)
    return {"ok": not blocked, "blocked": blocked, "token_present": token, "models": [r for r in rows if r["gate"] != "open"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="forge-recommend",
        description="Probe this machine and print the VF Studio models that fit it. Never downloads.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "A normal run probes this machine. --fixture is a synthetic capability profile for tests "
            "(nvidia-16gb, apple-24gb, amd-8gb, …), not a list of supported computers."
        ),
    )
    parser.add_argument("--json", action="store_true", help="print the machine and tiers as JSON")
    parser.add_argument("--ids", action="store_true", help="print model ids, space-separated, for fetch-models")
    parser.add_argument("--tier", default="recommended", choices=sorted(TIER_SETS),
                        help="which buckets --ids includes (default: recommended = essentials + quality)")
    parser.add_argument("--fixture", choices=sorted(FIXTURES),
                        help="synthetic hardware profile for tests; skips the live probe")
    parser.add_argument("--stack", help="stack root (manifest + disk). Default: this repo, or MEDIA_STACK, or ~/media-stack")
    parser.add_argument("--uncensored", action="store_true", help="include the labeled opt-in uncensored writer")
    parser.add_argument("--gpu", type=int, default=None, help="discrete GPU index to plan for (default: largest card)")
    parser.add_argument("--engines", action="store_true", help="print the per-modality engine map as JSON")
    parser.add_argument("--preflight", action="store_true", help="print license/gate notes for the ids about to be fetched; exit 3 if a login is required and no token is set")
    parser.add_argument("--every", action="store_true", help="with --preflight, check every manifest model instead of the recommended tier")
    parser.add_argument("--dry-run", action="store_true", help="accepted for symmetry; this command never downloads")
    parser.add_argument("check_ids", nargs="*", help="with --preflight, only these model ids")
    args = parser.parse_args(argv)

    stack = Path(args.stack).expanduser() if args.stack else stack_root()
    if args.fixture:
        machine = fixture_machine(args.fixture)
    else:
        machine = probe(stack)
    if args.fixture and args.stack:
        machine["disk_path"] = str(stack)
    if args.uncensored or os.environ.get("VF_UNCENSORED") == "1":
        machine["uncensored"] = True
    if args.gpu is not None:
        machine["gpu_index"] = args.gpu
    elif os.environ.get("VF_GPU", "").strip().lstrip("-").isdigit():
        machine["gpu_index"] = int(os.environ["VF_GPU"])
    manifest = load_manifest(stack / "models" / "manifest.json")
    if args.preflight and (args.check_ids or args.every):
        wanted = args.check_ids or [m["id"] for m in manifest.get("models") or []]
        report = preflight(manifest, wanted)
        json.dump(report, sys.stdout, indent=2)
        sys.stdout.write("\n")
        if not report["ok"]:
            print("fix: huggingface-cli login   or export HF_TOKEN   (never commit it). VF_SKIP_GATE=1 continues anyway.", file=sys.stderr)
            return 3
        return 0
    result = recommend(manifest, machine)
    if not args.fixture:
        try:
            outp = stack / "run" / "forge-engines.json"
            outp.parent.mkdir(parents=True, exist_ok=True)
            outp.write_text(json.dumps({"engines": result["engines"], "backend": result["engines"]["backend"]}, indent=2) + "\n")
        except OSError:
            pass
    if args.preflight:
        report = preflight(manifest, ids_for(result, args.tier if args.tier != "recommended" else "recommended"))
        json.dump(report, sys.stdout, indent=2)
        sys.stdout.write("\n")
        if not report["ok"]:
            print("fix: huggingface-cli login   or export HF_TOKEN   (never commit it). VF_SKIP_GATE=1 continues anyway.", file=sys.stderr)
            return 3
        return 0
    if args.engines:
        json.dump(result["engines"], sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    if args.ids:
        print(" ".join(ids_for(result, args.tier)))
        return 0
    if args.json:
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    sys.stdout.write(render_text(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
