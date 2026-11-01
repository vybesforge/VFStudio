#!/usr/bin/env python
"""meshcheck.py - is this mesh printable? (trimesh)

Usage:
  meshcheck.py model.stl            # report; exit 0 if printable, 1 if not
  meshcheck.py model.stl --fix      # try to repair (fill holes, fix normals/winding,
                                    #   drop degenerate/duplicate faces) and write
                                    #   model_fixed.stl (or --out PATH); exit 0 if the
                                    #   repaired mesh is printable
  meshcheck.py model.stl --json     # machine-readable report

Printable == watertight AND consistent winding AND volume > 0 AND at least 4 faces.
Exit codes: 0 printable, 1 not printable, 2 could not load file.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import trimesh


def load(path: str) -> trimesh.Trimesh:
    m = trimesh.load(path, force="mesh")
    if not isinstance(m, trimesh.Trimesh) or m.is_empty:
        raise ValueError("file did not load as a triangle mesh")
    return m


def report(m: trimesh.Trimesh) -> dict:
    ext = m.bounding_box.extents if len(m.vertices) else np.zeros(3)
    wt = bool(m.is_watertight)
    vol = float(m.volume) if wt else None  # volume is meaningless on an open mesh
    winding = bool(m.is_winding_consistent)
    r = {
        "triangles": int(len(m.faces)),
        "vertices": int(len(m.vertices)),
        "watertight": wt,
        "winding_consistent": winding,
        "volume_mm3": round(vol, 2) if vol is not None else None,
        "bbox_mm": [round(float(x), 2) for x in ext],
        "bodies": int(m.body_count),
    }
    r["printable"] = wt and winding and len(m.faces) >= 4 and (vol is not None and vol > 0)
    if not wt:
        # trimesh.repair.broken_faces lists faces that have an edge with != 2 adjacent faces
        try:
            r["broken_faces"] = int(len(trimesh.repair.broken_faces(m)))
        except Exception:
            pass
    return r


def fix(m: trimesh.Trimesh) -> trimesh.Trimesh:
    m = m.copy()
    m.remove_infinite_values()
    m.merge_vertices()
    m.update_faces(m.nondegenerate_faces())
    m.update_faces(m.unique_faces())
    m.remove_unreferenced_vertices()
    trimesh.repair.fill_holes(m)   # only closes small/simple holes
    trimesh.repair.fix_normals(m)  # also fixes winding + inverted shells
    if not m.is_watertight:
        # heavy repair: pymeshfix (MeshFix) rebuilds a watertight, manifold surface.
        # It keeps only the largest connected component unless joincomp=True.
        try:
            import pymeshfix
            mf = pymeshfix.MeshFix(np.asarray(m.vertices), np.asarray(m.faces))
            mf.repair(joincomp=True, remove_smallest_components=False)
            m = trimesh.Trimesh(mf.points, mf.faces, process=True)
            trimesh.repair.fix_normals(m)
        except ImportError:
            print("WARN: pymeshfix not installed; only basic repair applied", file=sys.stderr)
    if m.is_watertight and m.volume < 0:
        m.invert()
    return m


def fmt(r: dict) -> str:
    bb = " x ".join(f"{x:.2f}" for x in r["bbox_mm"])
    vol = f'{r["volume_mm3"]:.1f} mm^3' if r["volume_mm3"] is not None else "n/a (open mesh)"
    lines = [
        f'triangles      : {r["triangles"]}  (bodies: {r["bodies"]})',
        f'bbox (mm)      : {bb}',
        f'watertight     : {r["watertight"]}' + (f'  (broken faces: {r["broken_faces"]})' if "broken_faces" in r else ""),
        f'winding ok     : {r["winding_consistent"]}',
        f'volume         : {vol}',
        f'PRINTABLE      : {"YES" if r["printable"] else "NO"}',
    ]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mesh")
    ap.add_argument("--fix", action="store_true", help="attempt repair and write a fixed copy")
    ap.add_argument("--out", help="output path for --fix (default: <name>_fixed.stl)")
    ap.add_argument("--json", action="store_true", help="JSON output")
    a = ap.parse_args()

    try:
        m = load(a.mesh)
    except Exception as e:
        print(f"ERROR: cannot load {a.mesh}: {e}", file=sys.stderr)
        sys.exit(2)

    before = report(m)
    result = {"file": a.mesh, "before": before}
    final = before

    if a.fix:
        fixed = fix(m)
        after = report(fixed)
        out = a.out or str(Path(a.mesh).with_name(Path(a.mesh).stem + "_fixed.stl"))
        fixed.export(out)
        result["after"] = after
        result["fixed_file"] = out
        final = after

    if a.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"== {a.mesh}")
        print(fmt(before))
        if a.fix:
            print(f"== after --fix  -> {result['fixed_file']}")
            print(fmt(result["after"]))

    sys.exit(0 if final["printable"] else 1)


if __name__ == "__main__":
    main()
