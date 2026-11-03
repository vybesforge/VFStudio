"""inspect_joints — sanity-check a saved joint set against the mesh it belongs to.

  tools/.venv/bin/python tools/rig/inspect_joints.py <asset.glb> [--asset SLUG] [--views DIR]

Prints, per joint, how far it sits from the nearest surface point and how far it is from the
body's mid-depth, then writes annotated front/side images so a human can look at the set the
way the picker would place it. Joints are read in glTF space (Y up), which is what the room's
`worldToLocal` writes and what `scratch/rig_from_joints.py` expects.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

STACK = Path(__file__).resolve().parents[2]
RIG = STACK / "rig"


def load_gltf_vertices(src):
    import trimesh
    m = trimesh.load(str(src), force="mesh")
    v = np.asarray(m.vertices, dtype=np.float64)
    # blender space for the render manifest: (x, y, z)_gltf -> (x, -z, y)
    return v, np.column_stack([v[:, 0], -v[:, 2], v[:, 1]]), m


def nearest_surface(mesh, pts, samples=200_000, seed=0):
    """Distance from each point to the closest mesh surface point (sampled + vertices)."""
    tri = np.asarray(mesh.triangles)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(tri), size=min(samples, len(tri)))
    bary = rng.dirichlet((1, 1, 1), size=len(idx))
    surf = np.einsum("ij,ijk->ik", bary, tri[idx])
    cloud = np.vstack([np.asarray(mesh.vertices), surf])
    d = np.linalg.norm(pts[:, None, :] - cloud[None, :, :], axis=2)
    return d.min(axis=1)


def draw(viewdir, out_name, pts_gltf, names):
    from PIL import Image, ImageDraw
    man = json.loads((viewdir / "views.json").read_text())
    made = []
    for vname, tag in (("ny", "front"), ("px", "side")):
        view = next((v for v in man["views"] if v["name"] == vname), None)
        if view is None:
            continue
        im = Image.open(viewdir / view["file"]).convert("RGB")
        d = ImageDraw.Draw(im)
        ua, va, o = np.array(view["u"]), np.array(view["v"]), np.array(view["origin"])
        for name, g in zip(names, pts_gltf):
            p = np.array([g[0], -g[2], g[1]]) - o      # glTF -> blender space
            px = float(ua @ p) + view["u0"]
            py = float(va @ p) + view["v0"]
            d.ellipse([px - 5, py - 5, px + 5, py + 5], outline=(255, 60, 60), width=2)
            d.text((px + 7, py - 6), name, fill=(255, 200, 60))
        out = viewdir / out_name.format(tag=tag)
        im.save(out)
        made.append(str(out))
    return made


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--asset", default=None)
    ap.add_argument("--views", default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    src = Path(a.src).expanduser()
    asset = a.asset or src.stem.replace("_rigged", "")
    jf = RIG / f"joints_{asset}.json"
    if not jf.exists():
        sys.exit(f"no joint file: {jf}")
    joints = json.loads(jf.read_text())
    names = [k for k in joints if not k.startswith("_")]
    if not names:
        sys.exit(f"{jf} holds no joints")

    v, vb, mesh = load_gltf_vertices(src)
    pts = np.array([[joints[n]["x"], joints[n]["y"], joints[n]["z"]] for n in names])
    dist = nearest_surface(mesh, pts)
    lo, hi = v.min(axis=0), v.max(axis=0)
    size = hi - lo
    print(f"{src.name} · asset {asset} · {len(names)} joints · template {joints.get('_template', '?')}"
          f" · source {joints.get('_source', 'hand-picked')}")
    print(f"bbox  x {lo[0]:+.3f}..{hi[0]:+.3f}   y {lo[1]:+.3f}..{hi[1]:+.3f}   z {lo[2]:+.3f}..{hi[2]:+.3f}")
    print(f"{'joint':11s} {'x':>7s} {'y':>7s} {'z':>7s} {'d_surface':>10s} {'y_frac':>7s}")
    rows = []
    for n, p, d in zip(names, pts, dist):
        yf = (p[1] - lo[1]) / (size[1] or 1)
        rows.append({"joint": n, "x": round(p[0], 4), "y": round(p[1], 4), "z": round(p[2], 4),
                     "surface_mm": round(float(d) * 1000, 1), "height_frac": round(float(yf), 3)})
        flag = "  <-- off the mesh" if d > 0.25 * size[1] else ""
        print(f"{n:11s} {p[0]:+7.3f} {p[1]:+7.3f} {p[2]:+7.3f} {d * 1000:9.1f}mm {yf:7.3f}{flag}")

    # cheap sanity rules that caught real mistakes
    warns = []
    # Only a biped's spine is a vertical stack: on a quadruped the head and neck are
    # legitimately lower than the back, so that rule would cry wolf on every hog.
    order = ["hips", "spine", "chest", "neck", "head"] if joints.get("_template") != "quadruped" else []
    ys = [(n, joints[n]["y"]) for n in order if n in joints]
    for (a1, y1), (a2, y2) in zip(ys, ys[1:]):
        if y2 < y1 - 0.01:
            warns.append(f"{a2} sits BELOW {a1} (y {y2:+.3f} vs {y1:+.3f})")
    for side, other in (("L_", "R_"), ("R_", "L_")):
        pairs = [(n, n.replace(side, other)) for n in names if n.startswith(side) and n.replace(side, other) in joints]
        for n, twin in pairs:
            dy = abs(joints[n]["y"] - joints[twin]["y"])
            dx = abs(joints[n]["x"] + joints[twin]["x"])
            if dy > 0.05 or dx > 0.06:
                warns.append(f"{n}/{twin} are not mirrored: dy {dy:.3f} m, |x| mismatch {dx:.3f} m")
    for r in rows:
        if r["surface_mm"] > 250 * float(size[1]):
            warns.append(f"{r['joint']} is {r['surface_mm']:.0f} mm from any surface")
    if warns:
        print("\nsuspicious:")
        for w in warns:
            print("  -", w)
    else:
        print("\nsuspicious: nothing")

    viewdir = Path(a.views) if a.views else (STACK / "scratch" / "rig-views" / asset)
    if (viewdir / "views.json").exists():
        made = draw(viewdir, "check_{tag}.png", pts, names)
        for m in made:
            print("  overlay:", m)
    else:
        print(f"  (no views in {viewdir} — run auto_joints once to get renders for an overlay)")

    if a.json:
        print(json.dumps({"asset": asset, "joints": len(names), "rows": rows, "warnings": warns}))


if __name__ == "__main__":
    main()
