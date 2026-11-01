# Image → 3D asset in ComfyUI (Hunyuan3D 2.1)

Local, no cloud 3D service. ComfyUI 0.43+ ships every node below natively.

## Weights

| File | Source | Size | Where |
|---|---|---|---|
| `hunyuan_3d_v2.1.safetensors` | `Comfy-Org/Hunyuan-3D-2.1` | 7.4 GB | `ComfyUI/models/checkpoints/` |

One all-in-one checkpoint: `ImageOnlyCheckpointLoader` returns MODEL (slot 0),
CLIP_VISION (1) and VAE (2). No separate VAE/DINOv2 download is needed — the
loader pulls DINOv2 and ShapeVAE from inside the file at run time.

Download with `curl -fL --retry 3 -C -` from
`https://huggingface.co/Comfy-Org/Hunyuan-3D-2.1/resolve/main/hunyuan_3d_v2.1.safetensors`.

**For anything over ~2 GB, use `hf_transfer` instead of curl.** Plain curl sustained
2–3 MB/s on this machine; the Rust range-downloader measured **13.3 MB/s (~5×)** on the
same files, which turns an afternoon into half an hour.

```bash
~/.hermes/tools/uv-*/uv pip install --python ComfyUI/.venv/bin/python hf_transfer
# then, in the fetching process:
export HF_HUB_ENABLE_HF_TRANSFER=1
```

`hf_hub_download` mirrors the repo layout under `local_dir`, so point `local_dir` at a
scratch path and move the file into its `models/<kind>/` folder afterwards. Prefer one
file per invocation over a loop of parallel curls — concurrent downloads contend and
each one drops to curl speeds.

## Choosing an engine (measured, same input)

Three engines, one A-pose reference image, M3 Max 64 GB. This is what each actually
leaves on disk — the attribute columns matter more than the triangle count.

| Engine | Time | Tris | Textures | Normals | UVs | QC |
|---|---|---|---|---|---|---|
| Hunyuan3D **2.0** (`dit-v2_fp16`) | **148 s** | — | none | ✗ | ✗ | fail |
| Hunyuan3D **2.1** (`hunyuan_3d_v2.1`) | 281 s | 128,146 | 1 projected | ✗ | ✓ | fail |
| **TRELLIS.2** (shipped template) | 448 s | 699,800 | **3 PBR** | ✓ (+TANGENT) | ✓ | **PASS** |

- **TRELLIS.2 wins on quality per asset** and is the only one that passes the QC gate.
- **Hunyuan 2.0 is geometry only** — `POSITION` and nothing else: no normals, no UVs, no
  texture. Output is a blockout; budget a separate paint/render-normal pass before
  calling it an asset. Its head came out lumpy with ear-like protrusions and the feet
  merged into the floor.
- **Hunyuan 2.0 has three variants, not one:** `hunyuan3d-dit-v2_fp16` (single image),
  `hunyuan3d-dit-v2-mv_fp16` and `…-mv-turbo_fp16` (four views). All three are 4.59 GB.
- **2.0 is all-in-one despite appearances.** `Comfy-Org/Hunyuan-3D-2.0` publishes the
  files as `split_files/…/dit-…` with no separate VAE or vision encoder, but the DiT
  file drops into `models/checkpoints/` and `ImageOnlyCheckpointLoader` returns
  MODEL + CLIP_VISION + VAE from it exactly like 2.1. Use ComfyUI's
  `3d_hunyuan3d_image_to_model.json` template; it is a subgraph, so drive it through the
  UI like the TRELLIS graph rather than converting it to an API prompt.
- **2.1 must be decimated before unwrap** when you want texture: `--decimate 200000`
  then unwrap gave 4,163 charts in 18.5 s. Without decimate, `--no-unwrap` fails at
  `ApplyTextureToMesh: mesh has no UVs` — the unwrap is not optional if you ask for a
  texture.
- **None of the three invents what the photo never showed.** All three produced
  malformed feet and flat skin from a full-body reference; a human subject is the worst
  case for single-image reconstruction.

## Reference image requirements

Geometry is only as good as the input. Generate with the image model first, then
reconstruct:

- Full body in frame with margin; nothing clipped at the edges.
- All four legs separated from the torso and from each other — fused legs come
  back as a single fused limb.
- Seamless plain white background.
- **No floor shadow.** A cast shadow reads as geometry and deforms the underside.
  Say "no cast shadow" explicitly in the prompt; models add one by default.
- Side profile or three-quarter reconstructs better than head-on.
- Check the result with a vision pass before spending compute on the mesh: wrong
  subject class (a piglet when an adult was asked for) is cheaper to fix at the
  image stage.

## Graph — single view (default)

```json
{
 "1":  {"class_type": "ImageOnlyCheckpointLoader", "inputs": {"ckpt_name": "hunyuan_3d_v2.1.safetensors"}},
 "2":  {"class_type": "LoadImage", "inputs": {"image": "ref.png"}},
 "6":  {"class_type": "CLIPVisionEncode", "inputs": {"clip_vision": ["1",1], "image": ["2",0], "crop": "center"}},
 "10": {"class_type": "Hunyuan3Dv2Conditioning", "inputs": {"clip_vision_output": ["6",0]}},
 "11": {"class_type": "EmptyLatentHunyuan3Dv2", "inputs": {"resolution": 3072, "batch_size": 1}},
 "12": {"class_type": "KSampler", "inputs": {"model": ["1",0], "positive": ["10",0], "negative": ["10",1],
            "latent_image": ["11",0], "seed": 42, "steps": 20, "cfg": 8.0,
            "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0}},
 "13": {"class_type": "VAEDecodeHunyuan3D", "inputs": {"samples": ["12",0], "vae": ["1",2],
            "num_chunks": 8000, "octree_resolution": 256}},
 "14": {"class_type": "VoxelToMesh", "inputs": {"voxel": ["13",0], "algorithm": "surface net", "threshold": 0.6}},
 "15": {"class_type": "SaveGLB", "inputs": {"mesh": ["14",0], "filename_prefix": "3d/asset"}}
}
```

Conditioning outputs two CONDITIONING slots (positive 0, negative 1).
`cfg` 8.0 is the documented band (4–8); `sampler_name` and `denoise` are literal
input names — `sampler` is rejected.

## Adding texture

Insert between `VoxelToMesh` and `SaveGLB`:

```json
{
 "18": {"class_type": "LoadImage", "inputs": {"image": "ref.png"}},
 "16": {"class_type": "UnwrapMesh", "inputs": {"mesh": ["14",0], "segmenter": "pec",
            "resolution": 2048, "padding": 4, "weld_distance": 0.0001}},
 "17": {"class_type": "ApplyTextureToMesh", "inputs": {"mesh": ["16",0], "base_color": ["18",0]}},
 "15": {"class_type": "SaveGLB", "inputs": {"mesh": ["17",0], "filename_prefix": "3d/asset"}}
}
```

- `segmenter` accepts **only** `pec` or `adaptive`.
- The texture source can be the same image used for geometry — the spots/markings
  land on the mesh as a projection, so it reads correctly from the visible side and
  stretches on hidden faces. **Treat this projection as a preview, not a finished
  albedo.** Surfaces the photo never saw (far flank, belly, inner legs, top) sample
  the photo's background and come out white/blank. See the projection ceiling in
  SKILL.md: no parameter fixes it, only a 3D-aware paint stage does.
- `UnwrapMesh.resolution` is the atlas size, not a geometry quality dial. 4096 on a
  decimated 246k-face mesh produced a 4267×4332 atlas with ~4k charts and completed
  comfortably; the same atlas on an undecimated mesh is the OOM path.
- Optional PBR maps on `ApplyTextureToMesh`: `metallic`, `roughness`, `occlusion`,
  `normal_map` (each an IMAGE).

## Multi-view variant

Swap node `10` for:

```json
{"class_type": "Hunyuan3Dv2ConditioningMultiView",
 "inputs": {"front": ["6",0], "right": ["7",0], "back": ["8",0], "left": ["9",0]}}
```

Every slot is optional, so one view is legal. Only worth it when the four images
are the *same animal* — see SKILL.md: independently sampled views are not, and
mismatched views beat the single-view result into worse geometry.

## Measured on M3 Max (64 GB, MPS)

| Stage | Cost |
|---|---|
| Load checkpoint + DINOv2 + ShapeVAE | ~6 s, 5.8 GB + 0.6 GB + 0.6 GB resident |
| Sampling, 20 steps | ~86 s (~4.3 s/it) |
| Volume decode, 2122 chunks (octree 256) | ~1–2 min |
| Volume decode, 16,876 chunks (octree 512) | seconds — chunk count is not the bottleneck |
| `VoxelToMesh` at octree 512 | **dominates the run, and emits no progress output — reads as a hang** |
| Full octree-512 run, decimate 250k, 4096 atlas | ~13 min 15 s wall clock, 246k faces out |
| UV unwrap (LSCM) | **slowest stage at low face counts — minutes, single-threaded** |

At octree 512 the pipeline goes quiet for many minutes inside `VoxelToMesh`. Watch
`GET /queue` (`queue_running` still 1) and the ComfyUI pid's RSS instead of the
log, and never restart it as "hung" — restarting discards the whole run.

Whole pipeline with texturing runs in the ~10 minute class, unwrap dominating.
Bare geometry (skip `UnwrapMesh`) returns in minutes. If a run appears to stall,
check the log for `unwrap:` progress before assuming a hang.

## Failure modes

- **`HTTP 400` on submit with a `node_errors` body.** The body names the exact
  failing input and the valid combo list. Always read and print it — a client that
  swallows the body turns a one-line fix into guesswork. Wrap the POST so the
  response text is surfaced on `HTTPError`.
- **New checkpoint not in the loader's combo.** ComfyUI scans model folders at
  startup only. Restart to pick it up, but never mid-render — check the queue first.
- **Empty `outputs` and no GLB.** The prompt validated but the output node was
  ignored; look for `Output will be ignored` / `invalid prompt` in the ComfyUI log
  rather than in your own script.

## Verify the GLB before shipping it

```bash
head -c 4 asset.glb            # must print b'glTF'
```

Then confirm size and that the room's loader reports dimensions and triangle
count. A GLB that opens but has zero tris means the mesh stage produced an empty
voxel — raise `octree_resolution` or lower the `threshold`.
