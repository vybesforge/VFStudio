"""List mesh nodes in a GLB to spot strays."""
import json
import struct
import sys

for path in sys.argv[1:]:
    with open(path, "rb") as f:
        _, _, total = struct.unpack("<III", f.read(12))
        chunks = {}
        while f.tell() < total:
            cl, ct = struct.unpack("<II", f.read(8))
            chunks[ct] = f.read(cl)
            if cl % 4:
                f.read(4 - (cl % 4))
    g = json.loads(chunks[0x4E4F534A].decode("utf-8").rstrip("\x00 "))
    print(f"== {path}")
    for i, m in enumerate(g.get("meshes", [])):
        prims = m.get("primitives", [])
        counts = [g["accessors"][p["attributes"]["POSITION"]]["count"]
                  for p in prims if "POSITION" in p.get("attributes", {})]
        print(f"   mesh[{i}] {m.get('name')!r} prims={len(prims)} verts={counts}")
    for i, n in enumerate(g.get("nodes", [])):
        if "mesh" in n:
            print(f"   node[{i}] {n.get('name')!r} mesh={n['mesh']} skin={n.get('skin')}")
