# Asset QC gate (GLB before delivery)

Run the gate on the exported file, not on a render. Each check exists because the
corresponding defect actually shipped at least once.

| Check | Failure it catches |
|---|---|
| `NORMAL` attribute present | Mesh renders as a faceted low-poly toy at 94k tris because `SaveGLB` omits normals |
| `TEXCOORD_0` present | No UVs — cannot carry an atlas at all |
| Embedded image + texture | "Textured" GLB with an external or missing image |
| Albedo luminance stddev ≥ ~8 | A baked atlas that is visually blank (projection sampled the studio background) |
| Triangle count ≤ budget | Unshippable density; also predicts unwrap OOM |
| Largest bbox dimension sane (0.15–6 m) | Unit-normalised output silently entering a scene at 2 cm or 200 m |
| `animations` > 0 when animation was requested | Rig exported without its action |
| `JOINTS_0` + `WEIGHTS_0` | Skinned export that lost its skinning |

Exit non-zero on any hard failure so it can gate a pipeline. Keep soft signals
(dimension surprises, undecodable image) as warnings, not failures.

## GLB parsing — the offset that produced a false defect report

A GLB is a 12-byte header (`magic`, `version`, `length`) followed by chunks, each
prefixed by an 8-byte `(length, type)` header. **Consume those chunk headers.**
Reading the file remainder as the buffer starts 8 bytes early, which shifts every
vertex read by two floats and yields numbers that look plausible: real coordinate
ranges, smooth distributions, and a completely wrong verdict.

```python
chunks = {}
while f.tell() < length:
    clen, ctype = struct.unpack('<II', f.read(8))
    chunks[ctype] = f.read(clen)
    if clen % 4:
        f.read(4 - (clen % 4))      # chunk padding
json_chunk  = chunks[0x4E4F534A]
bin_chunk   = chunks.get(0x004E4942, b'')
```

Then resolve positions properly — accessor → bufferView, respecting both
offsets, with `byteStride` defaulting to 12 for tightly packed float VEC3:

```python
acc = js['accessors'][prim['attributes']['POSITION']]
bv  = js['bufferViews'][acc['bufferView']]
off = bv.get('byteOffset', 0) + acc.get('byteOffset', 0)
stride = bv.get('byteStride', 12)
```

Further traps:

- Check `componentType` (5126 = float) before unpacking; quantised meshes use
  shorts/bytes and `normalized` scaling.
- **Accessor `min`/`max` can disagree with the actual data.** They are metadata,
  not proof of range. Use them for a sanity check against your own sampled
  min/max, and treat disagreement as "parsing is wrong", not "asset is broken".
- Read every primitive, not just `meshes[0].primitives[0]`; material splits
  produce several and one may be a small subset that skews any ratio.

## Discipline: prove a detector before reporting from it

A new heuristic is a hypothesis about the asset, not a fact. Before telling the
user something is wrong with a shipped artifact:

1. Cross-check the reading against a **render** of the same file (ground truth
   the user can also see).
2. If they disagree, suspect the parser/detector first — welds, strides, chunk
offsets and subset primitives all produce confident nonsense.
3. Report a retraction as plainly as the original claim, and disable the
   suspicious check behind an env flag rather than leaving it as an authority.

A gate that contradicts a render costs more trust than it saves; a gate that
passes a blank texture costs a delivery.
