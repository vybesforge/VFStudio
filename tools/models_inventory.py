#!/usr/bin/env python3
"""models_inventory — reconcile ComfyUI/models on disk with models/manifest.json.

  tools/models_inventory.py            # human summary
  tools/models_inventory.py --json     # machine readable

Exit code 1 if the manifest references something that is not on disk.
Nothing is deleted or downloaded here; this only reports.
"""
import json
import os
import sys
from pathlib import Path

STACK = Path(os.path.expanduser("~/media-stack"))
MODELS = STACK / "ComfyUI" / "models"
MANIFEST = STACK / "models" / "manifest.json"
# folders that hold weights (skip bookkeeping folders)
SKIP = {"configs", "put_checkpoints_here", "split_files"}
EXTS = {".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".gguf", ".onnx", ".pkl", ".sft"}


def walk():
    out = []
    for d in sorted(p for p in MODELS.iterdir() if p.is_dir()):
        if d.name in SKIP:
            continue
        for f in d.rglob("*"):
            if f.is_file() and (f.suffix.lower() in EXTS or f.name.endswith(".gguf")):
                st = f.stat()
                out.append({
                    "folder": d.name,
                    "path": str(f.relative_to(MODELS)),
                    "gb": round(st.st_size / 2**30, 2),
                    "mtime": __import__("time").strftime("%Y-%m-%d", __import__("time").localtime(st.st_mtime)),
                })
    out.sort(key=lambda r: -r["gb"])
    return out


def main():
    disk = walk()
    man = json.load(open(MANIFEST))
    entries = man.get("models", [])
    by_path = {r["path"]: r for r in disk}
    tracked = {e["path"]: e for e in entries}

    missing = [e for e in entries if e["path"] not in by_path]
    untracked = [r for r in disk if r["path"] not in tracked]
    total = sum(r["gb"] for r in disk)

    if "--json" in sys.argv:
        print(json.dumps({
            "disk_total_gb": round(total, 1), "file_count": len(disk),
            "manifest_entries": len(entries),
            "missing_from_disk": missing,
            "on_disk_not_in_manifest": untracked,
            "by_folder": {f: round(sum(r["gb"] for r in disk if r["folder"] == f), 1)
                          for f in sorted({r["folder"] for r in disk})},
        }, indent=1))
    else:
        print("models on disk: %d files, %.1f GB" % (len(disk), total))
        print("manifest entries: %d  · missing on disk: %d  · untracked on disk: %d"
              % (len(entries), len(missing), len(untracked)))
        if missing:
            print("\nMISSING (manifest says we have it):")
            for e in missing:
                print("  %-42s %s" % (e["id"], e["path"]))
        if untracked:
            print("\nON DISK, NOT IN MANIFEST (largest first):")
            for r in untracked[:40]:
                print("  %7.2f GB  %s" % (r["gb"], r["path"]))
            if len(untracked) > 40:
                print("  … %d more" % (len(untracked) - 40))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
