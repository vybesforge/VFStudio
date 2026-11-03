#!/usr/bin/env python3
"""Detect this machine and install what fits.

  python3 tools/forge/install.py                  # print the plan
  python3 tools/forge/install.py --write-engines  # refresh run/forge-engines.json
  python3 tools/forge/install.py --apply          # write the map and install panel deps
  python3 tools/forge/install.py --apply --models # also fetch the essentials profile

Windows: install.ps1 calls this. Apple Silicon's brew path stays in install.sh
and calls --write-engines. CUDA / ROCm driver and PyTorch installs are printed,
not performed — those need the vendor packages for the card you actually have.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent))
import recommend as rec  # noqa: E402


def plan(machine: dict, manifest: dict) -> dict:
    if os.environ.get("VF_UNCENSORED") == "1":
        machine = dict(machine)
        machine["uncensored"] = True
    result = rec.recommend(manifest, machine)
    tier_ids = rec.ids_for(result, "essentials")
    report = rec.preflight(manifest, tier_ids)
    return {"result": result, "preflight": report, "essentials": tier_ids}


def render(blob: dict) -> str:
    result = blob["result"]
    eng = result["engines"]
    m = result["machine"]
    lines = [
        "VF Studio install plan",
        f"  os       {m.get('os')} {m.get('arch')}  {m.get('os_pretty') or ''}".rstrip(),
        f"  engine   {eng.get('backend')}   card {eng.get('gpu_index')} {eng.get('gpu_name') or ''}".rstrip(),
        "",
        "backends",
    ]
    for key in ("image", "video", "sfx", "music", "tts", "stt", "clone", "llm", "vision", "stems", "3d", "print"):
        slot = eng.get(key) or {}
        flag = "ready" if slot.get("runnable") else "stand-in"
        lines.append(f"  {key:<8} {slot.get('engine', '?'):<12} {flag:<8} {slot.get('note', '')}")
    lines.append("")
    if blob["preflight"]["blocked"]:
        lines.append("preflight: STOP — these need a Hugging Face login before fetch:")
        for i in blob["preflight"]["blocked"]:
            lines.append(f"  {i}")
        lines.append("  huggingface-cli login    or export HF_TOKEN     (never commit the token)")
        lines.append("  VF_SKIP_GATE=1 continues when you know the URL is public")
    else:
        notes = blob["preflight"]["models"]
        if notes:
            lines.append("preflight: license notes (fetch is not blocked)")
            for row in notes:
                lic = f" — {row['license']}" if row.get("license") else ""
                lines.append(f"  {row['id']}  {row['gate']}{lic}")
        else:
            lines.append("preflight: nothing in the essentials set needs a login")
    lines += [
        "",
        "next",
        "  bin/forge-recommend",
        "  bin/fetch-models --dry-run --profile essentials",
        "  bin/fetch-models --profile essentials",
        "  stack panel",
    ]
    if eng.get("backend") in ("cuda", "rocm"):
        lines.append("  ComfyUI needs a PyTorch build for this GPU. See INSTALL-UBUNTU.md sections 2, 5, and 6.")
        lines.append("  Voice is speaches. The writer and vision are llama-server, not MLX.")
    elif eng.get("backend") == "mlx":
        lines.append("  install.sh is the Homebrew path for Apple Silicon. Voice, writer, and vision stay on MLX.")
    else:
        lines.append("  No GPU was detected. The panel and the CPU tools still install; diffusion will not.")
    lines.append("")
    return "\n".join(lines)


def write_engines(stack: Path, blob: dict) -> None:
    path = stack / "run" / "forge-engines.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"engines": blob["result"]["engines"], "backend": blob["result"]["engines"]["backend"]}, indent=2) + "\n")


def apply(stack: Path, models: bool) -> int:
    venv = stack / "audio" / ".venv"
    py = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not py.exists():
        subprocess.check_call([sys.executable, "-m", "venv", str(venv)])
    subprocess.check_call([str(py), "-m", "pip", "install", "-q", "fastapi", "uvicorn"])
    print(f"panel deps installed in {venv}")
    if models:
        fetch = stack / "bin" / "fetch-models"
        if os.name == "nt":
            print("On Windows, run fetch-models from Git Bash:")
            print(f"  bash {fetch} --profile essentials")
            return 0
        return subprocess.call(["bash", str(fetch), "--profile", "essentials"], cwd=str(stack))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Detect this machine and print or apply the studio that fits.")
    p.add_argument("--fixture", choices=sorted(rec.FIXTURES), help="synthetic hardware profile (tests)")
    p.add_argument("--write-engines", action="store_true", help="write run/forge-engines.json and exit")
    p.add_argument("--apply", action="store_true", help="install panel dependencies for this OS")
    p.add_argument("--models", action="store_true", help="with --apply, also fetch the essentials profile")
    p.add_argument("--stack", default=None)
    args = p.parse_args(argv)
    stack = Path(args.stack).expanduser() if args.stack else rec.stack_root()
    manifest = rec.load_manifest(stack / "models" / "manifest.json")
    machine = rec.fixture_machine(args.fixture) if args.fixture else rec.probe(stack)
    blob = plan(machine, manifest)
    if args.write_engines and not args.fixture:
        write_engines(stack, blob)
        print(f"wrote {stack / 'run' / 'forge-engines.json'}")
        return 0
    sys.stdout.write(render(blob))
    if args.apply and not args.fixture:
        write_engines(stack, blob)
        return apply(stack, args.models)
    return 0 if blob["preflight"]["ok"] or args.fixture else 0


if __name__ == "__main__":
    raise SystemExit(main())
