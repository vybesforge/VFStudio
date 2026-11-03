"""center_joints — push surface-picked joints into the middle of the limb they belong to.

  tools/.venv/bin/python tools/rig/center_joints.py <asset.glb> [--asset SLUG] [--factor 1.0]
      [--radius 0.06] [--write] [--json]

Picking in the room means clicking the skin, so every joint ends up on the surface: bones then
run along the front of the body instead of through it. For each joint this finds the point
locally furthest from the surface — the inscribed-sphere centre, i.e. the medial axis of the
limb or torso at that spot — and moves the joint there (or `--factor` of the way there).

No normals and no rtree: trimesh's ray/proximity paths need `rtree`, which this venv does not
ship, and averaged vertex normals on a TRELLIS scan are noise. The search is a brute-force
max-min over a small cube around the joint, which is what "how far inside am I" actually
measures. Writes a timestamped backup under rig/attic/ before touching the file.
"""
import argparse
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np

STACK = Path(__file__).resolve().parents[2]
RIG = STACK / "rig"


def gltf_to_blender(v):
    return np.column_stack([v[:, 0], -v[:, 2], v[:, 1]])


def blender_to_gltf(p):
    return np.array([p[0], p[2], -p[1]])


def medial_point(mesh, p_gltf, span, radius_frac=0.10, iters=3, samples=7):
    """Point near p with the largest clearance that is *inside* the mesh.

    This deliberately assumes nothing about which axis is up or lateral: a rigged export can
    be rotated in the XZ plane (hog_quad_rig is ~45 degrees off), which wrecks any depth-axis
    or normals-based reasoning — a ray "inward" then travels along the body's diagonal. A
    brute-force max-min over a small cube, filtered by `mesh.contains`, is the axis-free
    version of the same idea: the winner is the centre of the thickest part of whatever body
    part the joint is in."""
    import trimesh
    p = np.asarray(p_gltf, dtype=np.float64)
    verts = np.asarray(mesh.vertices)
    R = radius_frac * span
    near = verts[np.linalg.norm(verts - p, axis=1) < 2.5 * R]
    if len(near) < 100:
        near = verts
    best, best_d, step = p, -1.0, R
    for _ in range(iters):
        ax = np.linspace(-step, step, samples)
        cand = np.stack(np.meshgrid(ax, ax, ax, indexing="ij"), -1).reshape(-1, 3) + best
        inside = np.zeros(len(cand), dtype=bool)
        for i in range(0, len(cand), 200):
            block = cand[i:i + 200]
            inside[i:i + 200] = trimesh.contains(mesh, block) if hasattr(trimesh, "contains") \
                else mesh.contains(block)
        if not inside.any():
            step *= 0.4
            continue
        sub = cand[inside]
        d = np.empty(len(sub))
        for i in range(0, len(sub), 128):
            block = sub[i:i + 128]
            d[i:i + 128] = np.linalg.norm(block[:, None, :] - near[None, :, :], axis=2).min(axis=1)
        top = np.argsort(d)[-6:]                     # best few, then stay near the pick
        pick = top[np.argmin(np.linalg.norm(sub[top] - p, axis=1))]
        best, best_d = sub[pick], float(d[pick])
        step *= 0.45
    if best_d < 0:
        return None, 0.0
    return best, 2.0 * best_d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--asset", default=None)
    ap.add_argument("--factor", type=float, default=1.0, help="0 = unchanged, 1 = mid-limb")
    ap.add_argument("--only", default=None, help="comma-separated joint names to touch")
    ap.add_argument("--radius", type=float, default=0.06, help="search radius as a fraction of span")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    import trimesh

    src = Path(a.src).expanduser()
    asset = a.asset or src.stem.replace("_rigged", "")
    jf = RIG / f"joints_{asset}.json"
    if not jf.exists():
        sys.exit(f"no joint file: {jf}")
    data = json.loads(jf.read_text())
    names = [k for k in data if not k.startswith("_")]

    m = trimesh.load(str(src), force="mesh")
    verts = gltf_to_blender(np.asarray(m.vertices))
    span = float(np.linalg.norm(verts.max(axis=0) - verts.min(axis=0)))
    radius = a.radius * span
    print(f"{src.name} · asset {asset} · {len(names)} joints · span {span:.3f} · search r {radius * 1000:.0f} mm")

    only = {s.strip() for s in (a.only or "").split(",") if s.strip()}
    unknown = only - set(names)
    if unknown:
        sys.exit(f"not in {jf.name}: {', '.join(sorted(unknown))}")
    if only:
        names = [n for n in names if n in only]
        print(f"  touching only: {', '.join(names)}")

    out, rows, moved = dict(data), [], 0
    for n in names:
        p_gltf = np.array([data[n]["x"], data[n]["y"], data[n]["z"]], dtype=np.float64)
        target, clearance = medial_point(m, p_gltf, span)   # already in glTF space
        if target is None:
            rows.append({"joint": n, "moved_mm": 0.0, "clearance_mm": 0.0, "note": "no local surface"})
            print(f"  {n:11s} left alone (not enough surface nearby)")
            continue
        q = p_gltf + (target - p_gltf) * float(a.factor)
        d = float(np.linalg.norm(q - p_gltf))
        out[n] = {"x": round(float(q[0]), 4), "y": round(float(q[1]), 4), "z": round(float(q[2]), 4)}
        moved += d > 1e-4
        rows.append({"joint": n, "moved_mm": round(d * 1000, 1), "clearance_mm": round(clearance * 1000, 1),
                     "note": ""})
        print(f"  {n:11s} {p_gltf[0]:+.3f},{p_gltf[1]:+.3f},{p_gltf[2]:+.3f} -> "
              f"{q[0]:+.3f},{q[1]:+.3f},{q[2]:+.3f}   moved {d * 1000:5.1f} mm"
              f"   clearance {clearance * 1000:5.1f} mm")

    print(f"moved {moved}/{len(names)} joints")
    if a.write and moved:
        attic = RIG / "attic"
        attic.mkdir(exist_ok=True)
        bak = attic / f"joints_{asset}.surface-{time.strftime('%Y%m%d-%H%M%S')}.json"
        shutil.copy(jf, bak)
        jf.write_text(json.dumps(out, indent=1))
        print(f"  backup {bak}\n  wrote   {jf}")
    elif moved:
        print("  dry run — pass --write to save")
    if a.json:
        print(json.dumps({"asset": asset, "moved": moved, "rows": rows}))


if __name__ == "__main__":
    main()
