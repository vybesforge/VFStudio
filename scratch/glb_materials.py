"""Report which GLB image each material slot actually binds.

qc_glb.py judges image[0], which is only correct when the base-colour texture
happens to be first. With a full PBR set (base colour + metallic/roughness +
normal) the exporter may reorder them, and an occlusion or metal-rough map is
legitimately flat — so the flat-texture check must follow baseColorTexture.
"""
import json
import struct
import sys

path = sys.argv[1]
with open(path, "rb") as f:
    _, _, total = struct.unpack("<III", f.read(12))
    chunks = {}
    while f.tell() < total:
        cl, ct = struct.unpack("<II", f.read(8))
        chunks[ct] = f.read(cl)
        if cl % 4:
            f.read(4 - (cl % 4))

gltf = json.loads(chunks[0x4E4F534A].decode("utf-8").rstrip("\x00 "))
images = gltf.get("images", [])
textures = gltf.get("textures", [])
print(f"{path}: {len(images)} images, {len(textures)} textures")
for i, im in enumerate(images):
    print(f"  image[{i}] name={im.get('name')!r} mime={im.get('mimeType')}")

for mi, mat in enumerate(gltf.get("materials", [])):
    pbr = mat.get("pbrMetallicRoughness", {})
    bc = pbr.get("baseColorTexture", {}).get("index")
    mrt = pbr.get("metallicRoughnessTexture", {}).get("index")
    nm = mat.get("normalTexture", {}).get("index")
    oc = mat.get("occlusionTexture", {}).get("index")

    def img(idx):
        if idx is None:
            return None
        src = textures[idx].get("source")
        return f"tex{idx}->image{src}"

    print(f"  material[{mi}] {mat.get('name')!r}: base={img(bc)} "
          f"metalRough={img(mrt)} normal={img(nm)} occlusion={img(oc)}")
