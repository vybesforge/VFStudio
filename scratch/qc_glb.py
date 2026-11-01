"""QC gate for any GLB before it reaches VR.

Every check here corresponds to a defect that actually shipped once:
  - a GLB with 94k triangles and no NORMAL attribute (rendered as a faceted toy)
  - a GLB with a "texture" that was visually blank (projection sampled the
    studio background)
  - assets normalised to a unit cube with no real-world scale

Usage:
  python qc_glb.py asset.glb [--max-tris 200000] [--json]

Exit code 0 = pass, 1 = fail. Prints reasons.
"""

from __future__ import annotations

import io
import json
import os
import struct
import sys
from pathlib import Path

TEX_MIN_STDDEV = 8.0     # luminance spread; a flat/blank bake is < 3
MAX_DIM_M, MIN_DIM_M = 6.0, 0.15


def parse_glb(path: Path):
    with open(path, "rb") as f:
        magic, version, length = struct.unpack("<III", f.read(12))
        if magic != 0x46546C67:
            raise ValueError("not a GLB (bad magic)")
        chunks = {}
        while f.tell() < length:
            clen, ctype = struct.unpack("<II", f.read(8))
            data = f.read(clen)
            chunks[ctype] = data
            if clen % 4:
                f.read(4 - (clen % 4))
    js = json.loads(chunks[0x4E4F534A].decode("utf-8").rstrip("\x00 "))
    bin_chunk = chunks.get(0x004E4942, b"")
    return js, bin_chunk


def image_bytes(js, bin_chunk, index):
    """Raw bytes of the embedded image, or None."""
    try:
        img = js["images"][index]
    except (KeyError, IndexError):
        return None
    if "bufferView" in img:
        bv = js["bufferViews"][img["bufferView"]]
        off = bv.get("byteOffset", 0)
        return bin_chunk[off:off + bv["byteLength"]]
    return None


def base_color_image_index(js):
    """Index of the image bound to baseColorTexture, or None.

    Judging images[0] is wrong on any asset with a full PBR set: exporters reorder
    images, and a normal or metallic-roughness map is legitimately flat. Following
    the material binding is the only correct way to find the albedo.
    """
    textures = js.get("textures", [])
    for mat in js.get("materials", []):
        idx = mat.get("pbrMetallicRoughness", {}).get("baseColorTexture", {}).get("index")
        if idx is None:
            continue
        if 0 <= idx < len(textures):
            src = textures[idx].get("source")
            if src is not None:
                return src
    return None


def tex_stats(js, bin_chunk):
    """(mean, stddev) of luminance for the base-colour texture, or None."""
    try:
        from PIL import Image
    except ImportError:
        return None

    order = []
    bc = base_color_image_index(js)
    if bc is not None:
        order.append(bc)
    order += [i for i in range(len(js.get("images", []))) if i != bc]

    for i in order:
        raw = image_bytes(js, bin_chunk, i)
        if not raw:
            continue
        try:
            im = Image.open(io.BytesIO(raw)).convert("L").resize((128, 128))
        except Exception:
            continue
        px = list(im.getdata())
        n = len(px)
        mean = sum(px) / n
        var = sum((p - mean) ** 2 for p in px) / n
        return mean, var ** 0.5
    return None


def slab_check(js, bin_chunk, sample=8000):
    """Detect flat slabs at the extreme top/bottom of the mesh.

    This is what actually caught the pedestal: a real animal's vertices spread
    evenly over its height, while a reconstructed ground plane piles ~20%+ of
    them into the bottom few percent. Unwelded GLBs (split at every UV seam)
    inflate counts at *any* coordinate, so a plain "many verts share a value"
    test mis-fires — an extreme-slab distribution does not.
    """
    try:
        prim = js["meshes"][0]["primitives"][0]
        acc = js["accessors"][prim["attributes"]["POSITION"]]
        bv = js["bufferViews"][acc["bufferView"]]
        off = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
        stride = bv.get("byteStride", 12)
        n = acc["count"]
        lo, hi = acc["min"], acc["max"]
        ys = []
        step = max(1, n // sample)
        for i in range(0, n, step):
            ys.append(struct.unpack_from("<fff", bin_chunk, off + i * stride)[1])
    except Exception:
        return None
    if len(ys) < 200:
        return None
    h = hi[1] - lo[1]
    if h <= 1e-6:
        return None
    band = h * 0.04
    low = sum(1 for y in ys if y < lo[1] + band) / len(ys)
    high = sum(1 for y in ys if y > hi[1] - band) / len(ys)
    if low >= 0.18 or high >= 0.18:
        return {"low_fraction": round(low, 3), "high_fraction": round(high, 3)}
    return None


def qc(path: Path, max_tris: int = 200000) -> dict:
    js, bin_chunk = parse_glb(path)
    problems, warnings = [], []

    attrs, tris, verts = set(), 0, 0
    mins, maxs = None, None
    for mesh in js.get("meshes", []):
        for prim in mesh.get("primitives", []):
            attrs |= set(prim.get("attributes", {}))
            idx = prim.get("indices")
            if idx is not None:
                tris += js["accessors"][idx].get("count", 0) // 3
            pos = prim["attributes"].get("POSITION")
            if pos is not None:
                acc = js["accessors"][pos]
                verts += acc.get("count", 0)
                if "min" in acc and "max" in acc:
                    lo, hi = acc["min"], acc["max"]
                    mins = lo if mins is None else [min(a, b) for a, b in zip(mins, lo)]
                    maxs = hi if maxs is None else [max(a, b) for a, b in zip(maxs, hi)]

    n_textures = len(js.get("textures", []))
    n_images = len(js.get("images", []))
    n_anim = len(js.get("animations", []))

    # --- hard failures -------------------------------------------------
    if "NORMAL" not in attrs:
        problems.append("no NORMAL attribute (will render flat/faceted — every viewer synthesises per-face normals)")
    if "TEXCOORD_0" not in attrs:
        problems.append("no TEXCOORD_0 (cannot carry a texture atlas)")
    if n_textures == 0 or n_images == 0:
        problems.append("no embedded texture/image (albedo-only or untextured)")

    stats = tex_stats(js, bin_chunk)
    if stats is None and (n_images and n_textures):
        warnings.append("could not decode the embedded image to check texture detail")
    elif stats is not None:
        mean, sd = stats
        if sd < TEX_MIN_STDDEV:
            problems.append(f"texture is visually flat (luminance stddev {sd:.1f} < {TEX_MIN_STDDEV}) — likely a blank or degenerate bake")

    if tris == 0:
        problems.append("no triangles")
    elif tris > max_tris:
        problems.append(f"{tris:,} triangles exceeds the budget of {max_tris:,} for VR")

    # Slab check is DISABLED by default: on this exporter's output it reports
    # ~98% of vertices at one height while the same file renders as a volumetric
    # animal. A gate that contradicts a render must not be trusted. Re-enable
    # only after the accessor parsing is reconciled against a known-good render.
    if os.environ.get("QC_SLAB_CHECK") == "1":
        slab = slab_check(js, bin_chunk)
        if slab:
            problems.append(
                f"flat slab at an extreme: {slab['low_fraction']*100:.0f}% of vertices in the "
                f"bottom 4% of height, {slab['high_fraction']*100:.0f}% in the top 4% — "
                "possibly a reconstructed ground plane/pedestal (EXPERIMENTAL check)")

    dims = None
    if mins is not None and maxs is not None:
        dims = [round(b - a, 3) for a, b in zip(mins, maxs)]
        biggest = max(dims)
        if biggest > MAX_DIM_M:
            problems.append(f"largest dimension {biggest} m — probably unit-normalised, not real-world scale")
        elif biggest < MIN_DIM_M:
            warnings.append(f"largest dimension {biggest} m — suspiciously small")

    if n_anim:
        pass  # informational
    return {
        "file": str(path),
        "pass": not problems,
        "problems": problems,
        "warnings": warnings,
        "stats": {
            "triangles": tris, "vertices": verts, "dimensions_m": dims,
            "textures": n_textures, "images": n_images, "animations": n_anim,
            "attributes": sorted(attrs),
            "texture_mean": round(stats[0], 1) if stats else None,
            "texture_stddev": round(stats[1], 1) if stats else None,
        },
    }


def main():
    args = [a for a in sys.argv[1:]]
    as_json = "--json" in args
    if as_json:
        args.remove("--json")
    max_tris = 200000
    if "--max-tris" in args:
        i = args.index("--max-tris")
        max_tris = int(args[i + 1])
        del args[i:i + 2]
    if not args:
        sys.exit("usage: qc_glb.py <file.glb> [--max-tris N] [--json]")

    results = [qc(Path(p), max_tris) for p in args]
    if as_json:
        print(json.dumps(results, indent=2))
    else:
        for r in results:
            s = r["stats"]
            head = "PASS" if r["pass"] else "FAIL"
            print(f"[{head}] {Path(r['file']).name}")
            print(f"       {s['triangles']:,} tris · {s['vertices']:,} verts · dims {s['dimensions_m']} m")
            print(f"       textures {s['textures']} · images {s['images']} · anims {s['animations']} · "
                  f"tex mean/std {s['texture_mean']}/{s['texture_stddev']}")
            print(f"       attrs {s['attributes']}")
            for p in r["problems"]:
                print(f"       ✗ {p}")
            for w in r["warnings"]:
                print(f"       ! {w}")
    sys.exit(0 if all(r["pass"] for r in results) else 1)


if __name__ == "__main__":
    main()
