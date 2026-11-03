#!/home/billie/media-stack/tools/.venv/bin/python
"""glb_material — rewrite GLB material factors in place (JSON chunk only, no re-encode).

  glb_material in.glb out.glb --metallic 0 --roughness 0.85 [--drop-metallic-map]

Why this exists: an image-to-3D bake *guesses* a metallic/roughness map from a
2D illustration. On a stylised character that guess lands around 25–30 % metallic,
and a metallic dielectric is dark and glossy — the render reads as grey plastic
with purple skin, and it gets blamed on the albedo, which is fine. For cloth, skin
and hair the honest answer is metallic 0. The base-colour, normal and occlusion
bindings are left exactly as the baker wrote them.

Touches only the JSON chunk; BIN chunk (geometry, images) is copied byte-for-byte.
"""
import argparse
import json
import struct
import sys

JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942


def read_glb(path):
    raw = open(path, "rb").read()
    magic, ver, total = struct.unpack("<III", raw[:12])
    if magic != 0x46546C67:
        sys.exit(f"not a GLB: {path}")
    off, chunks = 12, []
    while off < total:
        clen, ctype = struct.unpack("<II", raw[off:off + 8])
        off += 8
        chunks.append([ctype, raw[off:off + clen]])
        off += clen
        if clen % 4:
            off += 4 - (clen % 4)
    return chunks


def write_glb(path, chunks):
    body = b""
    for ctype, data in chunks:
        pad = (4 - len(data) % 4) % 4
        data = data + (b" " if ctype == JSON_CHUNK else b"\x00") * pad
        body += struct.pack("<II", len(data), ctype) + data
    total = 12 + len(body)
    open(path, "wb").write(struct.pack("<III", 0x46546C67, 2, total) + body)


def main():
    ap = argparse.ArgumentParser(prog="glb_material", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--metallic", type=float, default=0.0)
    ap.add_argument("--roughness", type=float, default=0.85)
    ap.add_argument("--drop-metallic-map", action="store_true",
                    help="also unbind metallicRoughnessTexture (occlusion stays)")
    a = ap.parse_args()

    chunks = read_glb(a.src)
    ji = next(i for i, (t, _) in enumerate(chunks) if t == JSON_CHUNK)
    gltf = json.loads(chunks[ji][1].decode("utf-8").rstrip("\x00 "))

    for mat in gltf.get("materials", []):
        pbr = mat.setdefault("pbrMetallicRoughness", {})
        before = (pbr.get("metallicFactor"), pbr.get("roughnessFactor"),
                  "metallicRoughnessTexture" in pbr)
        pbr["metallicFactor"] = a.metallic
        pbr["roughnessFactor"] = a.roughness
        if a.drop_metallic_map:
            pbr.pop("metallicRoughnessTexture", None)
        print(f"material {mat.get('name')!r}: metallic/roughness "
              f"{before[0]}/{before[1]} -> {a.metallic}/{a.roughness}"
              f"{' (metallic map unbound)' if a.drop_metallic_map else ''}")

    chunks[ji][1] = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    write_glb(a.dst, chunks)
    print(json.dumps({"ok": True, "out": a.dst, "bytes": len(open(a.dst, 'rb').read())}))


if __name__ == "__main__":
    main()
