---
name: local-media-stack
description: "Use when generating image/video/audio/3D locally on Apple Silicon. ComfyUI + mlx-audio stack, gen/fetch-models CLIs."
version: 1.0.0
author: Jimmy
license: MIT
platforms: [macos]
metadata:
  hermes:
    tags: [mlx, mlx-audio, comfyui, flux, tts, stt, music, apple-silicon, local-inference]
    category: media
---

# Local media stack (Apple Silicon)

> **Save deliverables under `~/media-stack/output/<kind>/`** (3d, image, video…) — that is where the VF Studio panel (http://127.0.0.1:8787) looks; files elsewhere never show up or preview there.

Two services cover every local generation need on an M-series Mac, and both speak
protocols Hermes already supports. Route Hermes at them instead of building tools.

| Need | Service | Hermes surface |
|---|---|---|
| Image / video | ComfyUI `:8188` | `image_gen` plugin (`image_gen.provider`) |
| TTS / STT / music / SFX | mlx-audio `:8000` | `tts` + `stt` via the `openai` provider |

## When to Use

- **Start with the `studio` skill** — it routes every asset request (image, video, 3D, VR,
  print, SFX, music, voice) to the right CLI and skill. This file is the deep reference for
  3D reconstruction, Blender repair, rigging, QC and the TRELLIS.2 UI-driven run.
- As of 2026-11-01 the **Hunyuan3D checkpoints referenced below are not on disk** (freed
  for space; TRELLIS.2 is the gold path). Add them to `models/manifest.json` and run
  `fetch-models` before following any Hunyuan recipe.

- Setting up local image, TTS, STT or music generation on an Apple Silicon Mac.
- Hermes' `image_generate` / `text_to_speech` / voice input must run locally
  instead of hitting a cloud API.
- A local generation service needs starting, stopping, or memory release.
- Writing a new `image_gen` backend plugin.

## Rules that always apply

- **Nothing in a delivered artifact may fetch from a CDN or a cloud API.** This
  user's whole setup is built on "no cloud inference, nothing phones home", and
  he will ask. Vendor every client-side dependency (see
  `references/webxr-asset-room.md`) and prove it rather than assert it: load the
  page and check `performance.getEntriesByType('resource')` returns no
  non-localhost URL.
- **Downloading assets from the internet is fine; generating them through a
  cloud API is not.** Free fonts, HDRIs, sample meshes and JS libraries are
  allowed raw material. Inference runs on his hardware, always.
- **State which half is local when reporting results.** Artifact generation is
  local; the session's own reasoning is cloud. Say so plainly instead of
  implying the whole pipeline is on-device.
- **Third-party pipeline docs are hypotheses, not requirements.** This user hands
  over specs and research explicitly as *suggestions* ("don't assume anything I
  paste is best"). Read the claimed numbers, then verify them on this machine
  before adopting the approach — adopt what measures better here, and say which
  claims you overrode and why. Conversely, a spec that independently confirms an
  expensive local finding (e.g. "this model is NVIDIA-only") is worth citing: it
  ends the investigation.

## Build it

```bash
mkdir -p ~/media-stack/{bin,logs,audio,control}
UV=$HOME/.hermes/tools/uv-*/uv   # bundling; or install uv

# Audio: one venv, one package, all four audio modalities
cd ~/media-stack/audio && $UV venv --python 3.12 .venv
$UV pip install --python .venv/bin/python "mlx-audio[server]" --prerelease=allow
$UV pip install --python .venv/bin/python "misaki[en]"   # REQUIRED for Kokoro TTS

# Images: ComfyUI + torch MPS
cd ~/media-stack && git clone --depth 1 https://github.com/comfyanonymous/ComfyUI.git
cd ComfyUI && $UV venv --python 3.12 .venv
$UV pip install --python .venv/bin/python torch torchvision torchaudio
$UV pip install --python .venv/bin/python -r requirements.txt
```

Use **Python 3.12** for both. MLX and torch wheels lag on 3.13/3.14; the
system python (3.9) is too old. Never touch system python.

## Route Hermes at it

mlx-audio is OpenAI-compatible, so no custom provider is needed for audio:

```bash
hermes config set tts.provider openai
hermes config set tts.openai.base_url http://127.0.0.1:8000/v1
hermes config set tts.openai.api_key not-needed      # TTS path REQUIRES a key
hermes config set tts.openai.model mlx-community/Kokoro-82M-bf16
hermes config set tts.openai.voice af_heart
hermes config set stt.enabled true
hermes config set stt.provider openai
hermes config set stt.openai.base_url http://127.0.0.1:8000/v1
hermes config set stt.openai.model mlx-community/whisper-large-v3-turbo-asr-fp16
```

`hermes config set` prints "not a recognized config key" for `base_url`,
`api_key` and `stt.provider` — **ignore it**. Those keys are read by the code
(`_resolve_openai_audio_client_config`, `_direct_openai_credentials`) but are
missing from the CLI's schema. Add `--force` to silence the notice.

STT accepts a **keyless** loopback base_url (`_is_local_or_private_url` sends a
`not-needed` placeholder itself). TTS does not — it needs the explicit dummy key.

## Image gen needs a plugin

The provider registry has no local backend, so write one:
`~/.hermes/plugins/image_gen/<name>/{plugin.yaml,__init__.py}`.

Contract (subclass `agent.image_gen_provider.ImageGenProvider`):
- class attrs `name`, optional `provider_id`; property `display_name`
- `is_available()` — **must not** make network calls (pickers call it constantly);
  return `ComfyUI dir exists`, not `server responds`
- `list_models()` — return an **explicit model table filtered by file presence**, never
  "every file in `models/checkpoints`". That folder also holds Stable Audio and ACE-Step
  checkpoints, and modern image models (Z-Image, FLUX.2 klein) are split files under
  `diffusion_models/` + `text_encoders/` + `vae/`, so a directory listing both lists
  audio models as image models and misses the real ones. Each entry names its files and
  its sampler defaults; the graph builder branches on the model id.
- `capabilities()` — `{"modalities": ["text"], "max_reference_images": 0}`
- `generate()` — return `success_response(...)` / `error_response(...)`
- module-level `register(ctx)` calling `ctx.register_image_gen_provider(...)`

`plugin.yaml` needs `kind: backend`. ComfyUI flow: `POST /prompt` with API-format
workflow `{class_type, inputs}` → poll `GET /history/{id}` → `GET /view?filename=...`.

**User plugins are opt-in.** A new plugin shows as `not enabled` in
`hermes plugins list` and silently never loads. Run `hermes plugins enable <name>`
before wiring `image_gen.provider`.

**A stale `image_gen.model` points at nothing.** The backend lists real checkpoint
filenames, so a value left over from a cloud provider (`krea-3` was still set on this
machine) matches no model and image generation fails with no useful message. After
enabling the plugin, set the model to an actual file from `models/checkpoints`
(`hermes config set image_gen.model flux1-dev-fp8.safetensors`) and confirm it is in
the provider's `list_models()` output.

## Models and generation from the CLI

`~/media-stack/models/manifest.json` is the single list of required model files
(id, folder-relative path, URL, size, role, plus a `fit` block). `bin/forge-recommend`
probes the machine and prints which ids to fetch; `fetch-models --profile auto` downloads
that set. `fetch-models` still downloads whatever is missing, sequentially and resumably;
`fetch-models --list` shows present/missing; `fetch-models --check` exits non-zero if anything is absent. `gen` (symlinked in
`~/.local/bin`) is one CLI for every ComfyUI pipeline — `gen image|control|upscale|
video|sfx|music|status` — and prints one JSON line with the output paths. Graph
parameters per model, the template-reading technique and which recipes are verified
live in `references/comfy-generation-recipes.md`. Use those two instead of hand-rolling
curl + /prompt each time.

Download hygiene:

- **Write to `<file>.part` and `mv` on success.** A loader combo lists any file in
  the folder, so a half-written `.safetensors` looks installed and fails at load time
  with an unhelpful header error. `.part` also makes `-C -` resume safe.
- **Never edit a shell script while it is running.** bash reads the file incrementally
  by byte offset, so an edit shifts the offsets and the running job executes garbage.
  Queue the fix for after the run, or write a new file.
- **Do not send `curl --progress-bar` to a log file** — it emits a carriage-return
  line per update and buries the useful lines. Use `-sS` in scripts and print your own
  start/done lines.
- **Edit the manifest freely while `fetch-models` runs** — it snapshots the list at
  start, so new entries are picked up by the next invocation, not mid-run.
- Keep the running total against the disk budget the user gave; the ComfyUI-native
  set for a full studio (fast image, editor, controlnet, video, SFX, music, upscalers)
  is ~85 GB on top of Flux/Qwen-Edit/TRELLIS.

### Installing GUI apps

Homebrew needs an interactive sudo password, which the terminal tool cannot supply.
Open a Terminal.app window for the user instead and read it back to see where it is:

```bash
osascript -e 'tell application "Terminal" to activate' -e 'tell application "Terminal" to do script "bash ~/path/install.sh"'
osascript -e 'tell application "Terminal" to get contents of tab 1 of window id <ID>' | tail -5
```

The `do script` call returns the window id. Tell the user it wants the login password
and that nothing echoes while typing — three wrong attempts is the usual outcome when
nobody told them which password. Without brew, `.app` bundles still install with
`hdiutil attach` + `cp -R` into `/Applications` + `xattr -dr com.apple.quarantine`,
no sudo needed (Blender was installed this way).

## Start/stop

Keep services out of Hermes' process tree: spawn with `start_new_session=True`,
write pid files, log to files. A panel that shells out `os.killpg` on the pid file
is enough — no launchd needed for on-demand use.

```bash
stack start comfy | stop comfy | status | logs comfy | free | music "caption"
```

`POST /free {"unload_models":true,"free_memory":true}` hands unified memory back
without stopping the server.

The two service commands, spelled out — neither is discoverable from a fresh
install without probing the package:

```bash
# mlx-audio: OpenAI-compatible TTS/STT server; models load per request
~/media-stack/audio/.venv/bin/python -m mlx_audio.server --host 127.0.0.1 --port 8000

# ComfyUI on MPS
cd ~/media-stack/ComfyUI && .venv/bin/python main.py --listen 127.0.0.1 --port 8188

# music generation is CLI-only (no HTTP route), and BOTH args are required
~/media-stack/audio/.venv/bin/mlx_audio.music.generate \
  --model mlx-community/MiniMax-Music3-8bit \
  --caption "lo-fi jazz, brushed drums" --lyrics "[instrumental]" --output out.wav
```

The music CLI rejects a missing `--lyrics` — pass `[instrumental]` instead of
omitting it. `mlx_audio.tts.generate`, `mlx_audio.stt.generate` and
`mlx_audio.sts.generate` follow the same pattern for one-off jobs.

## Performance on M-series unified memory

Measured on an M3 Max (64 GB, 40-core GPU), ComfyUI on MPS, 1024², timings
include model load:

| Model | Time | Resident weights |
|---|---|---|
| Z-Image-Turbo bf16, 8 steps | ~53 s (measured under download I/O; expect less idle) | ~12 GB + 8 GB Qwen3-4B |
| SDXL base fp16, 30 steps | ~71 s | ~7 GB |
| Flux dev fp8, 20 steps | ~226 s | 22.7 GB + 4.8 GB CLIP |

- Z-Image-Turbo is the default iteration pick (Apache-2.0, 8 steps, good adherence);
  Flux dev is the quality/text-rendering pick; SDXL only if already resident.
  FLUX.2 klein 4B shares the `qwen_3_4b` encoder with Z-Image, so the pair switch cheaply.
- Flux is the quality pick, SDXL the iteration pick. Switching between them pays
  the load cost again — ComfyUI evicts under memory pressure.
- A GGUF Q8 Flux build roughly halves that footprint and loads faster at a small
  quality cost — the right move when 27 GB resident leaves no headroom.
- **Never benchmark while a model download is writing to disk.** The same Flux
  job measured 381 s during a 6.5 GB download and 226 s minutes later on a quiet
  machine. A 3× "regression" that is really I/O contention sends you hunting a
  bug that does not exist. Re-measure on an idle box before calling anything slow.

## The reference image is the quality ceiling

Mesh resolution cannot invent anatomy the reference does not show, so spend the
effort here rather than downstream.

- **A single-image model needs an A-pose, and the pose is generation-time work.**
  Arms 30–45° clear of the torso (arms flush against the chest fuse into the mesh —
  the far side of each limb is never seen), legs straight and slightly apart, feet on
  the ground, whole figure in frame with margin. Slight 3/4 (15–30°) beats dead-on
  front, and both beat pure profile, which gives one silhouette and no depth cue. Long
  lens at chest height; a low or wide angle bakes perspective into the geometry. Flat
  even light and matte surfaces, because shading reads as surface and speculars read
  as noise. **Text-to-image models will not reliably obey a pose instruction** — Flux
  returned arms-at-sides on three of three attempts with the A-pose spelled out several
  ways, so cap pose re-rolls like any other stubborn trait and accept the neutral
  standing pose, or condition the pose explicitly (OpenPose ControlNet).
  - **Instruction editors drift on pose too — verify the generated pose before spending
  a recon on it.** Qwen-Image-Edit asked for an A-pose returned arms straight out at
  shoulder height (a T-pose); the wider silhouette pushes the subject smaller in the
  crop and the recon came back measurably *worse* (texture laplacian 637 vs 892 for the
  45° A-pose). Look at the pose, not the prompt. Related trap above 1 MP: `ImageScale`
  must follow `FluxKontextImageScale`, which clamps the reference to ~1 MP — without it
  a "2 MP" run silently samples at 1 MP.
- **img2img cannot re-pose a subject — never try to derive a turnaround with it.** It
  refines structure already present, so a frontal photo returns a frontal photo even at
  0.8 denoise (4 of 4 attempted "left/right/back" views came back facing camera).
  Generate the pose from text, or use pose conditioning (OpenPose ControlNet). And check
  the consumer first: TRELLIS.2 takes **one** image, so extra views buy nothing there.
- **A pose generated from text alone invents the person.** Flux text-to-image with
  "young woman, athletic build, dark brown hair in a bun" produced an East Asian face
  from a Hispanic/mixed source photo, because the face is the model's prior, not the
  subject. Never call an invented image "the reference" and never let a prompt
  description stand in for the subject's identity. The fix (check `fetch-models --list`
  for presence): **Qwen-Image-Edit 2509 + `Qwen-Edit-2509-Multiple-angles` LoRA** (19 GB
  diffusion model, 8.7 GB Qwen2.5-VL encoder, `qwen_image_vae`, 236 MB LoRA) is
  image-conditioned, so the A-pose and turnaround stay the same person.
- **Reconstruction loses the face even when the reference is right.** TRELLIS driven
  from the correct photo still returned a different woman (pale skin, platinum blonde).
  The head is ~40 px in a 1024² reference, so the texture stage renders a *plausible*
  face rather than the actual one — this is a pipeline property, not a texture setting,
  and no parameter fixes it. Add identity instead: condition the source image with
  Qwen-Image-Edit, or repaint the head region of the baked albedo from the photo and
  blend at the seam. Judge the result by cropping the head and asking a specific
  question (ethnicity, hair colour, marks); full-frame descriptions mislabel faces in
  both directions.
- **Know which model is an editor before promising an edit.** Flux dev cannot edit at
  all — text-to-image only; FLUX.1 Kontext (11.1 GB) is the Flux editor. Qwen-Image-Edit
  (~20 GB) follows instructions better and its Multiple-Angles LoRA (+0.27 GB) is the
  turnaround tool. For pose, OpenPose ControlNet over SDXL (2.33 GB, base already
  installed) beats every instruction editor, because editors preserve the structure they
  are given and a re-pose demands new anatomy. Sizes, verdicts and ready-to-paste A-pose
  prompts: `references/photo-to-3d-gold-standard.md`.
- **Background removal: the TRELLIS.2 template already does it internally**
  (`LoadBackgroundRemovalModel` → `RemoveBackground` → `ImageCropToMask`), so pre-cutting
  a clean-background source is redundant. Pre-cut only when a busy background masks
  badly, or on the Hunyuan path where it stops a backdrop and floor shadow being
  reconstructed as a slab fused to the subject's feet. `scratch/cutout_ref.py`, ~12 s,
- **Describe the distinguishing trait by analogy, in positive terms.**
  Guidance-distilled models (Flux dev, cfg 1.0) ignore negative prompts entirely,
  so "no cloven hooves, do not split the toe" changes nothing. Say what it should
  look like: "single solid horse-like hooves, one continuous unbroken hoof per
  leg". Breed-standard wording pulled from real sources still helps — look the
  breed up before writing the prompt.
- **But analogy is not a guarantee — cap the re-rolls at two.** A strong species
  prior can beat the prompt outright: six Flux seeds, both negative-style and
  horse-hoof analogy wording, returned cloven hooves every time. Re-rolling a
  seventh is not the fix. Pick the best-shaped candidate, ship it with the trait
  discrepancy stated plainly, and route the correction to a mask-based inpaint
  (Flux Fill) or a geometric fuse after meshing. Decide this after round two, not
  round six.
- **Verify the trait by zooming, not by looking at the finished frame.** A
  breed's defining detail is a few dozen pixels at 1024², and whole-image
  judgement calls it wrong in both directions. Crop to the region
  (`vision_analyze` with a `region` box over the feet/face/hands) and ask a
  question about that detail alone. Re-roll the reference if it fails; a trait
  that is wrong at the source is unfixable downstream.
- **Measure the pose and the margins in pixels; do not grade them by eye or by VLM.**
  Vision-model angle estimates contradict each other on the same image (one read of a
  wide A-pose said "45 degrees", another "arms almost horizontal"), and a whole-frame
  judgement cannot see a hand 30 px from the frame edge. `scripts/pose_measure.py
  ref1.png ref2.png` prints, per image, the subject bbox, left/right/top/bottom margins,
  each hand tip's distance to the edge, and the arm angle off vertical computed from
  shoulder row to hand row. Use it to choose between A-pose candidates and to prove a
  re-generation actually widened the arms.
- **When you show the user a crop for review, crop from a measured bbox and never
  resize to a square.** Both times a reviewer said "the head is stretched" / "that is
  only half a face", the asset was fine and the preview was wrong: a rectangular crop
  forced into a square distorts it, and a hand-picked top-22% box clips at nose height.
  Derive the region from the subject mask (top of subject + head-height fraction), keep
  the crop's own aspect ratio, and state the region in the message.
- **Generate several seeds and choose by eye.** Three to four candidates cost a
  few minutes and are cheaper than any repair pass.

## 3D assets (image → mesh)

ComfyUI 0.43+ ships the 3D nodes natively — query `/object_info` for anything
matching `3d|hunyuan3d|mesh|voxel|trellis` (83 nodes on 0.43) instead of
installing custom nodes.

- **TRELLIS.2 is the installed, gold-standard path; Hunyuan weights come and go** —
  check `models/checkpoints` before promising a Hunyuan run rather than trusting this
  text. **Hunyuan3D 2.1 is one all-in-one file**: `hunyuan_3d_v2.1.safetensors` from
  `Comfy-Org/Hunyuan-3D-2.1` (7.4 GB) into `models/checkpoints`. It loads via
  `ImageOnlyCheckpointLoader` and yields MODEL, CLIP_VISION and VAE together —
  no separate VAE or vision-model download.
- **Single-view conditioning is the reliable default.** `Hunyuan3Dv2Conditioning`
  takes one CLIP_VISION_OUTPUT. `Hunyuan3Dv2ConditioningMultiView` takes optional
  `front`/`left`/`back`/`right`, but only pays off with a *genuinely consistent*
  turnaround. Independently generated views are not one: same prompt, fixed seed,
  only the view clause changed, still returned a different animal per view, because
  a seed pins the sampling trajectory, not the identity across poses. Mismatched
  views reconstruct worse than a single good image — so reach for MultiView only
  with a real turnaround (a 3D-aware generator, or one image edited into the other
  angles), never four fresh samples.
- **Hunyuan3D 2.0 is not a four-photo model.** `Comfy-Org/Hunyuan-3D-2.0` ships three
  split DiTs: `hunyuan3d-dit-v2_fp16` (single image), `hunyuan3d-dit-v2-mv_fp16` and
  `…-mv-turbo_fp16` (four views). Select the variant that matches the input count you
  have. **It is all-in-one despite the packaging:** the repo lists no VAE or vision
  encoder, but the DiT file goes in `models/checkpoints/` and
  `ImageOnlyCheckpointLoader` returns MODEL + CLIP_VISION + VAE from it exactly like
  2.1. Drive ComfyUI's `3d_hunyuan3d_image_to_model.json` template (a subgraph, so
  through the UI) rather than converting it to an API prompt.
- **Pick the engine from what it leaves on disk, not from the triangle count.** Same
  input, measured here: Hunyuan 2.0 148 s but `POSITION` only (no normals, no UVs, no
  texture — a blockout); Hunyuan 2.1 281 s, 128k tris, one projected texture, still no
  normals; TRELLIS.2 448 s, 700k tris, 3 PBR maps, the only one that passes QC. Table in
  `references/image-to-3d.md`.
- **Every comparison run must write to its own path.** The Hunyuan script families
  copy their result to `vr/pig.glb` by default, which is the room's live asset — a
  three-engine bake-off silently replaces what the user is looking at. Give the fetch
  step an explicit output argument (`--out vr/hy21_hero.glb`) and treat `vr/pig.glb` as
  production only.
- **Use ComfyUI's venv for any PIL/image script**; the mlx-audio venv has no PIL and
  dies at import.
- **Texturing works locally**: `VoxelToMesh → UnwrapMesh → ApplyTextureToMesh`
  with `base_color` wired to a generated image bakes the reference onto the mesh as
  base colour. `ApplyTextureToMesh` also accepts optional `metallic`, `roughness`,
  `occlusion` and `normal_map` images. Treat a PBR result as achievable, not free.
- `UnwrapMesh`'s `segmenter` accepts only `pec` or `adaptive`. Any other value
  rejects the entire prompt as an unrecognised combo option.
- Output comes from `SaveGLB` with a `filename_prefix` such as `3d/<name>`, and
  lands in `ComfyUI/output/3d/`.

The full node-by-node graph, measured timings and failure modes are in
`references/image-to-3d.md`.

## VR asset test room

The room lives in `~/media-stack/vr/` and loads any `pig.glb` beside it. Serve it
from the panel's `/vr/` mount — **one origin, never a second port.** This user asks
for consolidation by preference ("a bit cleaner"), so fold new pages in as tabs
rather than standing up another server.

Vendoring steps, the GLB auto-fit trick and the offline verification are in
`references/webxr-asset-room.md`.

**`PANEL_HOST=0.0.0.0` does not make VR work from another machine.** A plain
`http://<LAN-IP>` is not a secure context, so `navigator.xr.requestSession` fails
there — only localhost/127.0.0.1 or HTTPS qualify. To test on the Windows/SteamVR
box, copy `vr/` over and open it on that box's own localhost. The LAN mount is for
desktop inspection of the room, nothing more.

## Control panel and resource monitoring

One FastAPI file, `~/media-stack/control/panel.py`, serves the whole UI on `:8787`
with tab sections in a single HTML string (Services / VR Room / Resources).
Mount static files with `app.mount("/vr", StaticFiles(directory=..., html=True))`.

- Poll `/api/resources` on a timer, and only while that tab is visible.
- **GPU utilisation is readable without root** on Apple Silicon:

```bash
ioreg -r -d 1 -w 0 -c IOAccelerator | grep PerformanceStatistics
# "Device Utilization %", "Renderer Utilization %", "Tiler Utilization %",
# "In use system memory", "Alloc system memory"
```

  Parse those for a real GPU gauge. CPU from `top -l 1 -n 0`, memory from `vm_stat`
  pages × page size, swap from `sysctl -n vm.swapusage`.
- Show **swap in use** beside memory — on unified memory it is the honest early
  warning that a loaded model is squeezing the machine.
- **The panel and ComfyUI are independent processes.** The panel dying while ComfyUI
  still answers is normal; a `000`/empty response from `:8787` with a 200 from `:8188`
  means restart `control/panel.py`, not that the stack is down. Probe the two services
  separately instead of concluding the machine is broken.
- Bind loopback by default; make LAN exposure an explicit opt-in env var.

## Hunyuan3D pitfalls that cost real time

Weights, the full API-format graph and per-stage timings live in
`references/image-to-3d.md`. Reference point: **~146 s** for a 503k-triangle mesh
at octree 256 on an M3 Max.

1. **Confirm a new weight file is visible before restarting anything.** Current
   ComfyUI re-lists model folders on request — files downloaded while the server ran
   validated and executed with no restart — so check
   `GET /object_info/<LoaderNode>` for the filename first and restart only if it is
   missing (a restart kills any in-flight job).
2. **`UnwrapMesh` segmenter enum is `pec` or `adaptive`** — anything else is
   rejected. Read the error; it names the valid list.
3. **`UnwrapMesh` on a dense mesh will OOM the server.** A 256-octree pig
   produced **381,878 UV charts**; chart packing reached 78% and ComfyUI died
   with a leaked-semaphore warning at ~64 GB RAM. The geometry had already
   completed. Either skip unwrap (`ApplyTextureToMesh` accepts a raw mesh) or
   reduce face count first.
   **Decimate before unwrap; do not lower the octree to buy unwrap headroom.**
   Charts scale with faces, so a heavier-but-decimated mesh unwraps far more
   cleanly than a coarse one: 246k faces decimated from an octree-512 volume
   produced **3,971 charts**, while 140k faces from a coarser volume produced
   **139,502**. Chart count follows face count and topology quality, not the
   voxel resolution. `octree_resolution` hard-caps at **512** on the node; reach
   it and decimate down.
4. **Native Hunyuan3D gives geometry only** — no texture stage. For skin use
   `ApplyTextureToMesh(mesh, base_color=LoadImage(your reference))`, which also
   takes optional metallic/roughness/occlusion/normal maps.
5. **Multi-view needs genuinely consistent views.** Four independent Flux
   renders share a prompt, not an identity — MV conditioning on them mangles
   the result. Use one strong side-on view, or generate a real turnaround.
6. **Hunyuan normalises output to ~[-1, 1]** (a ~2 unit cube). Scale it in the
   scene, not by editing the mesh.

## Blender repair pass (fixes what the generator gets wrong)

Install: the .dmg from download.blender.org → `cp -R /Volumes/Blender/Blender.app
/Applications/`. **Never symlink Blender into PATH** — a symlink breaks the
bundle-relative Python lookup and it dies with `Failed to import encodings
module`. Ship a wrapper script that `exec`s `/Applications/Blender.app/Contents/MacOS/Blender`
and unsets `PYTHONHOME`/`PYTHONPATH`/`VIRTUAL_ENV` first; `~/media-stack/bin/blender`
does exactly that.

Symptom this fixes: a ComfyUI GLB that renders as a flat, faceted white/charcoal
toy despite having 94k triangles and a `baseColorTexture`.

Root causes, both confirmed by parsing the GLB:

1. **No `NORMAL` attribute at all** — Hunyuan's `SaveGLB` omits normals, so every
   viewer synthesises flat per-face normals and the mesh reads as low-poly.
2. **`ApplyTextureToMesh` bakes a projection that can be nearly empty** — it
   samples the whole reference, including the white studio background.

Repair (`blender_repair.py`): clear custom split normals → weld → decimate →
planar-project the reference onto the mesh → bake base colour + AO → `shade_smooth`
→ export GLB.

**Traps:**
- glTF import writes custom split normals; `shade_smooth` is a no-op until you
  run `bpy.ops.mesh.customdata_custom_splitnormals_clear()`.
- Do **not** add a `SMOOTH_BY_ANGLE` modifier to "fix" smoothing — at the default
  30° it re-splits normals and puts the faceting straight back.
- Blender's render output path must be **absolute**; a relative path fails with
  `cannot save: 'file.png'`.

### Texture projection has a hard ceiling

Projecting a photograph onto a reconstruction can only paint surfaces the
photograph actually saw. The far flank, belly, inner legs and every upward-facing
surface have no source pixels, so they sample whatever the photo's background
was — usually white. The asset then reads as "white body with dark patches" and
no parameter fixes it. Four attempts, each failing differently:

| attempt | result |
|---|---|
| BOX/triplanar, scale 2.2 | tiled the photo into repeated subject silhouettes |
| BOX/triplanar, scale = 1/extent | still tiled |
| BOX + `extension = 'EXTEND'` | stopped repeating, but most samples were background |
| planar UV projection along the width axis | correct alignment on the profiled side, no coverage elsewhere |

**Planar projection is the best of them and still incomplete — use it to verify
geometry, not to ship a hero asset.** When the surface must be fully painted the
answer is a 3D-aware paint model, and the TRELLIS 2 template is the one that
works here: **16 min 16 s produced 700k triangles with three PBR textures and a
continuous coat — no white patches, no tiling.** That is the measured result, not
a hope. Hunyuan3D-2.1 paint via MLX is the alternative. State this to the user as
a known limitation with the fix named; do not iterate projection parameters.

Two sub-bugs that make planar projection look worse than it is:

- **Crop to the subject's bounding box first.** Planar mapping normalises the mesh
  bbox against the *whole* image, so studio margin around the animal is projected
  onto its back — the asset reads as light back / dark belly. A 1024² cutout
  carried 249 px of white above the subject; crop to it (`crop_tight.py`) and the
  same projection lands correctly.
- **Do not flip V.** Blender's V axis already runs bottom-to-top; writing
  `1.0 - v` inverts the paint, which the user will report as "the paint is
  upside down" before you spot it yourself.

Rigging, walk-cycle authoring and glTF animation export are in
`references/blender-authoring.md` — including why bone placement must treat Z as
up and why welding has to precede `separate(type="LOOSE")`.

## Asset QC before delivery

Run a gate on the exported GLB, not on the render. `scratch/qc_glb.py` checks the
things that actually shipped broken: missing `NORMAL`, missing `TEXCOORD_0`, no
embedded image, texture luminance stddev (a "textured" GLB whose albedo is
visually blank), triangle budget, real-world scale, and animation count.

**Judge the base-colour image, not `images[0]`.** On a PBR asset the exporter
reorders images and the normal or metallic-roughness map is legitimately flat, so
an index-0 check fails a perfectly good asset (stddev 4.8 on a normal map against
22.7 on the real albedo). Resolve
`materials[].pbrMetallicRoughness.baseColorTexture.index` → `textures[idx].source`
and measure that image. `scratch/glb_materials.py` prints the binding map.

**Stddev proves the albedo is not blank; laplacian variance proves it is not soft.** They
answer different questions and the second is the one that decides whether a higher-quality
rebuild actually improved anything. `scripts/texture_diff.py A.glb B.glb` prints
`laplacian_var` beside mean and std per file — higher means more high-frequency detail.
Any claim that a heavier rebuild "looks worse" needs that number before it is repeated:
three separate renders in this stack read as flatter or low-detail while the texture was
measurably sharper, because a dim rear view and warm light are not a texture comparison.

**A new detector must be proven against ground truth before you report its
findings.** A height-distribution heuristic flagged the approved asset as having
a pedestal fused to its feet; the same file rendered as a clean volumetric
animal. The detector was wrong (unwelded vertices plus an 8-byte GLB chunk-header
offset in the analysis script), and the retraction cost more trust than the check
saved. Cross-check any structural verdict against a render and an independent
parse; if they disagree, the detector is wrong until proven otherwise. Ship a
suspicious check disabled behind an env flag rather than as an authority.

**Verify skinning by measuring vertex displacement, not by rendering frames.**
Renders mislead in both directions: a correctly skinned asset looked fully static
from a 3/4 view while 380k vertices were moving 0.33 m. A GLB can carry a full
animation clip and still be rigid, so clip count proves nothing.

Two ready-to-run probes ship with this skill — use them rather than re-deriving
the scripts under deadline:

- `scripts/test_deform.py` — evaluates the mesh through the depsgraph across
  frames and prints `max_delta` / `verts_moved>5mm`; exits non-zero when nothing
  moves.
- `scripts/audit_weights.py` — leg-weight per height band, the real check for
  "legs claim the body"; exits non-zero when weight leaks above 70% height.

- **Import the largest mesh, not `meshes[0]`.** A skinned GLB imports with a stray
  42-vertex helper object first, so taking meshes[0] measures nothing and
  "proves" a working rig is broken.
- **Bone-heat weighting fails silently on dense meshes.** On a 700k-tri
  reconstruction Blender prints `Bone Heat Weighting: failed to find solution`,
  leaves the vertex groups present but **empty**, and the exporter then writes no
  skin at all (`Mesh_0 has no skin`). Checking that the group *names* exist passes
  even when this happens. Count vertices with `weight > 1e-5` per bone and fall
  back to `proximity_weights()` in `animate_asset.py` (numpy point-to-segment,
  two-bone blend, bucketed `group.add` calls — per-vertex Python over 400k verts
  never finishes).
- **Rotate limbs about a world axis converted into bone space.** Bone roll is
  undefined unless set explicitly, so `rotation_euler.x` on a leg bone swings it
  sideways instead of fore/aft. Use
  `local_axis = pb.bone.matrix_local.to_3x3().inverted() @ world_axis` with
  `rotation_mode='QUATERNION'`.
- **Gate leg weights to anatomical regions, and damp the second-nearest bone.**
  Nearest-bone binding lets a long leg segment claim the snout and back, so half
  the body rides the legs and shears apart. Restrict each leg to below the hip
  line and its own quadrant with a blend ramp, and subtract damped leg weight on
  *both* the nearest and second-nearest assignment (nearest-only leaves up to 0.5
  leg weight high on the back). Check leg weight per height band; a spine bob
  makes displacement spread a misleading metric. Recipe in
  `references/blender-authoring.md`.
- **Normalise scale before rigging.** Reconstructions come back at arbitrary units
  (TRELLIS normalises to ~1 m). Pass the target length and scale the object, then
  re-read the bbox — legs placed from a stale bbox land in the wrong place.
- **On a reconstructed mesh, weight per ISLAND, not per vertex.** Image-to-3D output
  is a soup of ~1,500 loose islands; per-vertex weighting tears wherever one island
  spans two bones, which reads as geometry smeared across the screen and is not
  fixed by smoothing. Bind each island to its dominant bone. Measured: 123.5× →
  **1.00×** max edge stretch, 3,905 → **0** edges over 2×. Trade-off to state
  plainly: limbs move as rigid chunks, not deforming skin.
- **Gate smearing on edge stretch, not on renders.** A wrong-bone vertex pulls its
  edges past rest length, so `max(now/rest)` and the count over 2× are the honest
  gate. Renders hide it from most angles and displacement spread misleads whenever
  the spine bobs.
- **Count limbs before rigging; the generator may have added one.** A fixed
  four-quadrant split cannot see a fifth leg — it averages its centroid into a real
  one and the rig places a bone between two legs. Count connected columns in the
  ankle slab, and delete the surplus limb rather than rigging around it.
- **Let this user place the joints; do not keep tuning heuristics.** Auto-placement
  cannot express an asymmetric or malformed mesh, and he proposed the right fix
  himself. Ship a browser joint picker that saves per-asset joint files, then build
  the armature from those points. It is embedded in the VR room so it works on any
  loaded asset. Architecture, coordinate conversions and pitfalls:
  `references/joint-picker.md`.
- **When a locality gate "does not work", check whether the gate line cuts through
  the thing it protects.** A head gate placed at the neck (0.84 along) locked out a
  front leg sitting at 0.87 and starved it to 273 verts. Place anatomical boundaries
  from measured limb columns, and confirm what a metric's selection actually
  contains before reporting its verdict.

- **Render a multi-view comparison with the lights riding the camera.** Key and fill
  pinned in world space leave the far side of the asset in shadow, and a shaded
  surface reads as a *different material*, not as less light: a green crop top and
  light-blue jeans came back black-and-black from the rear and looked precisely like
  a texture hallucinated differently front-to-back. Re-derive the key/fill position
  from each view's own azimuth (and put a rim light opposite the camera) before judging
  albedo; only equal exposure on every side makes a colour difference a defect.
  `scripts/render_views.py` does front / left / back / right / 3-4 with per-view
  lighting — use it instead of hand-placing cameras.
- **Use the right renderer for the question.** `render_views.py` / `render_asset.py` are
  EEVEE comparison tools — fast, and flat enough that a user reads them as an untextured
  base mesh. For anything shown to the user, render with `scripts/render_hero.py`
  (Cycles, AgX, studio sweep, per-view key/fill/rim, SSS nudge):
  `bin/blender -b -P scripts/render_hero.py -- out.glb outdir --views front,threequarter,head
  --size 1000x1400 --samples 128` → ~60-90 s per view.

GLB parsing gotchas and the full check list are in `references/asset-qc.md`.

## Photo → 3D: the gold-standard recipe

The approved asset (699,804 tris, 3 PBR maps, continuous coat, sha256 `773c5fd37e8c`)
lives at `~/media-stack/gold-standard/hog_trellis2_GOLD.glb`. The full ordered recipe —
reference prompt, cutout, tight crop, UI-driven TRELLIS.2 run, verification gates,
measured timings — is in `references/photo-to-3d-gold-standard.md`.

**Treat that file as the reference point, not a starting point.** It ships with its
fifth leg because that is what the generator produced; judge new experiments against
its texture stddev (22.7/19.9), attribute set and surface continuity. Copy it forward
for any experiment; never overwrite it.

## TRELLIS 2: use the shipped template, do not hand-build it

### Driving it through `/prompt` instead of the browser (verified)

The UI route below works but is fragile; there is a cleaner one. The template's own
`MeshToFile3D` emits `FILE_3D_GLB`, and **`SaveGLB` accepts that type** (`output_node:
true`). So: convert the shipped template to API format, add one `SaveGLB` fed by the node
that feeds `Save3DAdvanced.model_3d`, and delete the viewer nodes
(`Save3DAdvanced`, `Preview3DAdvanced`, both `Preview3DAdvanced` copies) plus the dead
Pixal3D/MoGe branch (`319, 55, 56, 242, 298`). The authored CFG structure stays intact, so
the noise-atlas failure mode does not appear. Working script: `scratch/run_trellis2_hq.py`.

- **A `COMFY_DYNAMICCOMBO_V3` input is the option KEY plus namespaced sub-inputs.**
  `RemeshMesh.sign_mode` = `"solid"` with `"sign_mode.fill": 20.0, "sign_mode.qef": false`
  (not a nested dict — that fails at *execution* with `execute() missing 1 required
  positional argument: 'sign_mode'`; not bare sibling `fill`/`qef` — that fails
  validation). Same rule for `DecimateMesh.placement_mode` (`"qem"` +
  `"placement_mode.line_quadric_weight"`, `…feature_edge_quadric_weight`,
  `…feature_edge_min_dihedral_deg`, `…clamp_v_to_edge`). Read the namespace from
  `/object_info/<Node>`, walk `input.required[k][1].options[].inputs.required`.
  **Validate before submitting**: a DynamicCombo left unset is not caught by the converter
  and only explodes after 20+ minutes of sampling.
- **`gen --out` creates a DIRECTORY.** `gen upscale`/`gen video --out out.png` writes
  `out.png/<prefix>_0000N_.png`, it does not name the file. Move the inner file out and
  `rmdir` the wrapper.

### Unwrap: weld first or the atlas is mush
The default `weld_distance 0.0002` left TRELLIS output unwelded and produced **per-triangle
charts**: 4096² atlas measured laplacian **168** against **892** on the approved asset, and
visually ~80% fragmented colour blobs. `weld_distance 0.001` on the same mesh gave
`1,194,140 faces -> 3,581 charts, atlas 4190x4194` and a coherent atlas. If an atlas looks
like smeared confetti, check chart count in the log line
`[uv_unwrap] N faces -> M charts` before touching bake resolution.

### Cost: unload first, then trust the step timer
A head-only recon ran **867 s/step** while the box had 10 GB swap in use (vision VLM +
image models resident). After `POST :8787/api/studio/unload-all` (47 GB freed) the same
profile ran at 8.5 s/step for the structure stage. Sampling cost also tracks the
`Trellis2UpsampleStage.target_resolution` far more than the bake size — dropping 1536→1024
took a head texture stage from 220 s/step to a finishable run.


ComfyUI installs the official graph at
`ComfyUI/.venv/lib/python3.12/site-packages/comfyui_workflow_templates_json/templates/3d_pixal3d_trellis2_image_to_model.json`.
Hand-assembling the same nodes from `/object_info` looks right and produces
garbage: the texture decode comes out as noise and bakes into a scrambled atlas
(abstract yellow/teal blocks, stripes, or terrazzo speckle). `scratch/run_trellis2_hq.py`
drives that exact template through `/prompt` by re-pointing its mesh at `SaveGLB`, and
is the proven path — see below. `scratch/run_trellis2.py` (browser/CDP) still works as a
fallback but has not been needed since the API route was verified.

What the template does that a naive graph does not:

- **Guidance is emulated, not passed as cfg.** Structure and shape run through
  `CFGOverride(cfg=1, start 0.667/0.769)` → `RescaleCFG(0.7/0.5)` → then
  `ModelSamplingSD3(5)` for structure only. The texture KSampler's own cfg is **1.0**.
  Raising cfg to 7.5 on a raw UNET does not substitute — it yields stripes.
- **A second KSampler refines the upsampled latent** and *that* is what
  `Trellis2TextureStage.shape_latent` must receive. Feeding the raw upsample output
  straight in is the biggest single cause of noise atlases.
- **Background is removed first** (`LoadBackgroundRemovalModel` → `RemoveBackground`
  → `ImageCropToMask`), then that cropped image conditions the model.
- **`BakeTextureFromVoxel` takes `reference_mesh`** plus mesh + voxel_colors, and
  emits 3 images: base colour, metallic, roughness — all consumed by
  `ApplyTextureToMesh` alongside AO (`BakeAmbientOcclusion`) and a real normal map
  (`BakeNormalMapFromMesh`). Base colour alone leaves the asset flat and faceted.
- **`MeshSmoothNormals(crease_angle=180)` last** is what removes the faceted look;
  `SaveGLB` writes no `NORMAL` attribute on its own.

**The template as shipped cannot be queued through `/prompt` — re-point its mesh at
`SaveGLB` and it can.** Two blockers, both confirmed against `/object_info` and the
server log:

- `Save3DAdvanced` requires a `viewport_state` (`LOAD_3D`) socket that only the web
  frontend injects, so it cannot be constructed from a script.
- **No output node accepts MESH.** `MeshToFile3D` reports `output_node=False`, so with
  the UI-only savers pruned it never executes on its own. The prompt then reports
  `status_str=success` in 0.02–8 s having run nothing at all, with only
  `PreviewImage`/`MaskPreview` entries in `/history` and no file in `output/3d/`.
  **Treat "success but no 3D file written" as a failed run** — check for the output
  file, never the status alone.

**Fix — feed the mesh to `SaveGLB` instead.** `MeshToFile3D` emits `FILE_3D_GLB` on its
`model_3d` output and `SaveGLB` accepts `FILE_3D_GLB` in its `mesh` input, so the node
that fed `Save3DAdvanced.model_3d` can feed a `SaveGLB` instead:

1. Convert the template's UI graph to an API prompt (widgets in declaration order; skip
   the `control_after_generate` / `image_upload` pseudo-widgets).
2. Read `prompt['322'].inputs['model_3d']` (the `Save3DAdvanced` link) — the
   `[node, slot]` of the final `MeshToFile3D` — **before** deleting anything.
3. Add `SaveGLB(mesh=<that link>, filename_prefix='3d/<name>')`.
4. Delete the viewer/saver nodes (`322` Save3DAdvanced, `323` + `246`
   Preview3DAdvanced) and the uninstalled branch (`319`, `55`, `56`, `242`, `298`),
   then unlink any remaining input that still points at a deleted id.
5. Keep `CFGOverride` / `RescaleCFG` / `ModelSamplingSD3` and the second (upsample)
   `KSampler` exactly as authored — they are the reason hand-built graphs bake noise
   atlases.

This keeps the authored graph, so it invalidates nothing said below about guidance
emulation. `scratch/run_trellis2_hq.py` implements it and sets the HQ profile by node
id (`312` ImageCropToMask, `94` Trellis2UpsampleStage, `3/18/23/12` the four KSamplers,
`241` RemeshMesh, `186` DecimateMesh, `288` PrimitiveInt → unwrap + colour bake, `233`
AO, `224` normal map, `261` RenderUVAtlas).

**Proven end to end**, same input, HQ profile: `status_str=success` *and* an 82 MB
`pepper_hq_00001_.glb` on disk, `qc_glb.py` PASS at **1,194,140 tris / 725,075 verts /
3 PBR maps / `NORMAL, POSITION, TANGENT, TEXCOORD_0` / texture std 23.8**. Two notes
from that run: the same graph re-submitted with identical inputs finishes in ~4 min
because ComfyUI reuses the cached structure/upsample stages (only remesh, decimate,
bakes and save re-run), so a timed run is not a cold-cache number; and after any
change to a wired node the run can take 25+ min again.

**Import hazard:** `scratch/run_trellis2.py` parses `sys.argv` at import time and
*deletes* `--image` / `--refname` from it, so importing it for its converter silently
strips your own CLI flags and argparse dies with "the following arguments are
required". Save `sys.argv`, replace it with `[argv[0]]` around the import, restore it
after.

Fallback if you would rather drive the browser (CDP recipe and code in
`references/trellis2-ui-run.md`): open
`http://127.0.0.1:8188`, fetch
`/templates/3d_pixal3d_trellis2_image_to_model.json` (served directly — not under
`/api/`), call `app.loadGraphData(wf)`, set `PrimitiveBoolean` to `true`, point
`LoadImage` at the reference, then `app.queuePrompt(0, 1)`. The frontend supplies
`viewport_state` itself. A 66-node graph takes a few seconds to load, longer than
the CDP eval timeout: fire it off unawaited and poll a global flag.

Mute the dead branch before queueing — node ids 55, 56, 242, 298, 319
(`LoadMoGeModel`, `MoGeInference`, `MoGeGeometryToFOV`, `Pixal3DConditioning`, the
Pixal3D `UNETLoader`). Those weights are not installed, and **validation covers the
whole prompt, not just the selected switch branch**, so the job fails even though
the switch makes them unreachable. `node.mode = 2` mutes a node; compare ids as
strings (`String(node.id)`) or the loop silently matches nothing and nothing is muted.

If you must build an API prompt anyway:

- Seed widgets carry an extra UI-only value (`fixed`/`randomize`) that must be skipped.
- **`COMFY_DYNAMICCOMBO_V3` inputs are `"<combo>": "<option key>"` plus NAMESPACED
  `"<combo>.<sub>": value` keys — neither sibling keys nor a nested dict works.**
  Confirmed on `RemeshMesh.sign_mode` (options `udf`/`sdf`/`solid`; `solid` needs
  `fill`, `qef`) and `DecimateMesh.placement_mode` (options `midpoint`/`qem`; `qem`
  needs `line_quadric_weight`, `feature_edge_quadric_weight`,
  `feature_edge_min_dihedral_deg`, `clamp_v_to_edge`):

  ```python
  # CORRECT
  {"sign_mode": "solid", "sign_mode.fill": 20.0, "sign_mode.qef": False}
  {"placement_mode": "qem", "placement_mode.line_quadric_weight": 0.0,
   "placement_mode.feature_edge_quadric_weight": 0.0,
   "placement_mode.feature_edge_min_dihedral_deg": 30.0,
   "placement_mode.clamp_v_to_edge": True}
  ```

  Both wrong shapes are silent disasters, not loud failures: bare sibling keys
  (`fill`/`qef` at the top level) fail validation with `Required input is missing:
  fill / qef`, and a nested dict fails at *execution* with `RemeshMesh.execute()
  missing 1 required positional argument: 'sign_mode'` — after the samplers have
  already run. Either way ComfyUI drops every output node and still returns
  `status_str=success` with no file written. Derive the names from
  `GET /object_info/<Node>` (`sign_mode[1].options[].inputs.required`) and remember
  `finalize_prefix` joins with `.`.
- **Guard the whole prompt for unset DynamicCombos before submitting.** Walk every
  node's `/object_info` schema, and for each `COMFY_DYNAMICCOMBO_V3` input assert the
  base key holds a valid option key *and* every sub-input of that option is present as
  `"<combo>.<sub>"`. Run it at build time and raise — otherwise the failure surfaces
  20+ minutes into a run, after sampling.
- Set the remaining `RemeshMesh` base inputs by name: resolution 768, band 1.0,
  project_back 0.0, fix_poles false, smooth_iters 20, drop_small_components 0.01,
  precluster_max_verts 20000000.
- Template defaults are 700k faces / 4096 atlas. Scale down to ~200k / 2048 for a VR
  asset, up via the HQ profile above for a hero asset — see that table for which knobs
  actually buy quality.

## TRELLIS 2 quality profiles

Three measured profiles on the same A-pose input. Pick by intent, not by taste.

| knob | VR-floor | default | HQ |
|---|---|---|---|
| `ImageCropToMask` | — | 1024² | 1536² |
| `Trellis2UpsampleStage` | — | 1536 | 2048 |
| steps (structure / upsample / texture) | — | 12 / 20 / 12 | 20 / 28 / 20 |
| `RemeshMesh` resolution | — | 768 | 1024 |
| `DecimateMesh` | ~200k | 700k | 1.2M |
| `UnwrapMesh` | 2048 | 2048 | 4096 |
| `BakeAmbientOcclusion` | — | 1024 | 2048 |
| `BakeNormalMapFromMesh` | — | 2048 | 4096 |
| `BakeTextureFromVoxel` | 2048 | 4096 | 4096 |

Same input, measured end to end: default **699,890 tris / 9m32s / texture laplacian 663**;
HQ **1,199,384 tris / 25m17s / laplacian 892** — +35% texture detail and +71% geometry
for 2.6× the wall time.

- **The geometric win comes from `RemeshMesh` resolution plus the decimate budget, not
  from the samplers.** Raising sampler steps alone changes little a human can see; raise
  remesh first and decimate to preserve it.
- **The colour bake is already maxed at 4096.** Going to 8192 costs minutes and buys
  nothing at 1.2M faces — spend the resolution on AO and normals, which carry the
  perceived surface relief.
- **Predict an unwrap OOM from UV *chart count*, not face count.** 1.2M faces unwrapped
  at 4096 inside ~41 GB, while 380k charts from a coarser volume killed the process on
  the same 64 GB box.
- **Unwrap must weld coincident vertices first, or the atlas is mush regardless of profile.**
  `UnwrapMesh`'s `weld_distance` defaulted to **0.0002**, which charts the TRELLIS mesh
  per-triangle: the 4096 albedo then bakes into dark noise on black (measured laplacian **168**
  against **892** on the approved asset) while the run still reports success. Set
  `weld_distance: 0.001` and `padding: 2` on the unwrap node (`196` in the shipped template) in
  the prompt you submit, and verify it in the **submitted** dict — a fix present in the script but
  absent from the queued prompt costs a full 52-minute run.
- **Judge a bake on the model, not on the atlas image.** A flat 4096 atlas reads as "noise" or
  "mush" in both directions, because coherent charts are still an abstract collage. Render the GLB
  with its materials (EEVEE, world light + sun, ortho front/side) and ask per region: the real
  verdict looks like "dark back, tan belly, brown hooves, pink snout, mane ridge — all in place,
  detail soft", not "is this noise".
- **TRELLIS `SaveGLB` writes `metallicFactor 1.0 / roughnessFactor 1.0`.** Metallic 1 on a hide
  renders as dull metal in every glTF viewer, which reads as a broken texture. When staging a bake
  for review, rewrite the material to `metallic 0.0 / roughness 0.85` (python: `pygltflib` load →
  edit `pbrMetallicRoughness` → save) and say that you changed it.
- **State the ceiling rather than hunting more settings.** Past HQ, fingers, toes, hair
  strands and skin pores need retopo or manual sculpt: the head is ~40 px in the
  reference, so no sampler recovers detail that was never photographed. More resolution
  improves the *surface*; it does not invent anatomy.

## Concurrent sessions edit the same files

This user runs a local/desktop session and the gateway (Telegram) at the same
time, both with terminal access to `~/media-stack`. Expect `scratch/*.py` to
change under you mid-task and expect runs you did not launch in `/history`.
Put new work in a **new file** rather than editing one the other surface is
editing, and check `ls -la` mtimes before trusting a script's contents.

**Long batches must survive a server restart.** ComfyUI can drop and come back mid-run;
a batch script that holds one `urlopen` call per job dies with
`ConnectionRefusedError` and takes the remaining queue with it. Wrap every API call in
a retry with backoff (`tries=6`, sleep `10 * attempt`), make the batch **resumable**
(skip a job whose output file already exists), and append each finished job to a manifest
JSON as you go — then a restart costs one image, not the batch. Measured here: a 4-step
Qwen edit job is ~150 s, so a 30-image set is ~75 min and is worth structuring for
restarts rather than running as one long loop.

**Defer to the queue before submitting.** One GPU, several writers. Poll
`GET http://127.0.0.1:8188/queue` until `queue_running` and `queue_pending` are
both empty, then submit; give the wait an opt-out flag (`--now`) rather than
baking it out. A prompt submitted while the other surface is clearing the queue
can disappear entirely: it is absent from `/queue`, absent from `/history`, and
the submitting script then polls forever. Expose occupancy in the panel
(`/api/comfy/job` → running/pending counts, node count, output prefix, prompt id)
so a human or another agent can see the box is busy instead of guessing.

## Versioning the stack

`~/media-stack` is its own git repo (~23 tracked files, ~6 MB including the two
shippable GLBs). Ignore `ComfyUI/` (a clone with its own `.git`), `audio/.venv/`,
`models/`, `ComfyUI/output/`, `logs/`, `run/` and `scratch/*.png|glb|wav|json`; keep
`bin/`, `control/`, `vr/` (minus the experiment GLBs), the scripts and the docs.

- **gitignore patterns take no trailing comment.** `ComfyUI/   # upstream clone` is a
  single literal pattern that never matches, so the clone gets staged as a gitlink and
  every later commit warns about an embedded repository. Undo with
  `git rm -r --cached -f ComfyUI` and put the comment on its own line.
- **Pin the clone's commit in a file, not a submodule.** `git -C ComfyUI rev-parse HEAD
  > COMFYUI_COMMIT` records what the stack was built against without dragging a
  submodule into a repo that only needs to reproduce one checkout.
- Amend rather than stack fix-up commits while the first commit is still local.

## Pitfalls

1. **Kokoro fails with `ImportError: misaki`** — install `misaki[en]`; the
   `mlx-audio[server]` extra does not pull it. Symptom: HTTP 200 with 0 bytes.
2. **First call is slow, then fast.** Kokoro ~45 s cold / ~140 ms warm; Whisper
   ~18 s cold. Don't benchmark the first request.
3. **`image_gen.provider` pointing at a stopped service** should produce a
   "not running" error that names the start command — never fall back to cloud silently.
4. **Flux fp8 all-in-one is 17 GB**, not 12 GB; budget download time accordingly.
   `flux1-dev-fp8.safetensors` works with plain `CheckpointLoaderSimple`.
5. **Flux sampling differs from SDXL**: cfg `1.0`, steps 20, sampler `euler`,
   scheduler `simple`. Running Flux at cfg 7 burns the image. Detect by filename.
5b. **KSampler input names are exact**: `sampler_name` (not `sampler`) and
   `denoise` is required. A `sampler` key fails validation with
   "Required input is missing: sampler_name" and the job silently produces no
   output node result. Check `/object_info` for the real required-input list
   before hand-building any workflow.
6. **mlx-audio needs ffmpeg on PATH** for mp3/flac/ogg output. The bundled
   binary lives in `~/.hermes/tools/ffmpeg-*/`; prepend it in the service env.
7. **`mlx_audio.server` picks models per request** by HF repo id — no restart to
   switch models, but every distinct model stays resident until evicted.
8. Verify STT end-to-end through Hermes' own code path, not just curl:
   `transcription_tools.transcribe_audio(path)` with the runtime venv python
   (`hermes doctor` prints the venv path). The bare `~/media-stack/audio` venv
   cannot import Hermes modules.
9. **Restart ComfyUI only when a model is provably not listed** (see Hunyuan
   pitfall 1 — newer builds rescan on request). If a restart is needed, check the
   queue first and restart while idle; never restart to "pick up" a model mid-job.
10. **A skill's frontmatter `name:` must match its directory name exactly, case
    included.** `skill_view` reports "ambiguous duplicate" for `Blender/` vs `blender/`
    when there is only ONE directory on this case-insensitive filesystem and the
    frontmatter says `name: Blender`. Fix by editing the frontmatter name to the
    directory's spelling; never delete a case-only "duplicate" — it is the skill.
11. **A face cannot be reconstructed inside a full-body recon.** The face gets ~5%
    of the atlas and ~120 px in the reference — eyes bake as black voids. Raising the
    atlas to 8192 changes nothing (measured: laplacian 892 -> 889): detail here is
    **source-limited, not atlas-limited**, so spend effort on input pixels, never on
    atlas size. The fix is a **head-only recon** from the highest-res photo available,
    then a merge by **enclosure**: scale the detail head just enough to cover the
    body's head (start ~1.03 of the measured head width) so the original becomes
    hidden interior geometry. Cutting both at the neck always leaves a visible rim ring.
    **Judge the margin at two framings.** A 10% enclosure margin reads as an oversized
    head in a full-body render while looking correct in a head close-up — head *size*
    is a whole-figure question, face *detail* is a crop question, and one frame cannot
    answer both.    `scripts/merge_head_overlay.py` does the measured fit and the enclosure
    merge — use it instead of re-deriving the alignment, which burns several attempts.
    **Prove the bust asset standalone before merging it into anything.** Render the head recon
    on its own first; if the hair is torn, the eyes are metallic, or the surface is fragmented
    at that framing, the merge amplifies it — measured on a full-body human: a 250k-tri bust
    recon from a 2108² neck-up crop merged at 1.03× read as an oversized head on the figure and
    fragmented across the skull, and the user rejected it in favour of the unmerged body asset.
    The merge is a *format* fix (detail head over coarse head), not a quality fix: on humans the
    face stays source-limited, so say that instead of promising the merge solves it. A bust
    recon is also the slowest TRELLIS job in this stack (90 min at upsample 1024 / remesh 320),
    so decide from a standalone render of a cheap pass, not from hope.
12. **TRELLIS texture-stage cost explodes on small subjects — check BOTH the upsample
    target and resident memory before blaming remesh.** A head-only job at remesh 1024
    ran 400-440 s/step (2h35m); at remesh 384 it ran 3.4 s/step. The full body is fine
    at 1024. But the same kind of bust also measured **867 s/step** at remesh 320 with
    `Trellis2UpsampleStage` 1536 while a vision model held ~10 GB of swap — after
    `POST /api/studio/unload-all` (47 GB returned) and upsample 1024 it ran **~200
    s/step**, and a first pass at ~9 s/step. So: unload everything first, print
    `sysctl -n vm.swapusage` before submitting, and treat the upsample target as the
    main cost driver. A 16-step texture stage at 200 s/step is ~50 min — budget it or
    cut steps rather than watching it drift.
13. **Verify the graph before queueing via the web UI.** ComfyUI's frontend restores
    the last-used workflow, so a `queuePrompt()` fired after a template load can run
    the wrong graph and silently write a PNG instead of a GLB. Assert
    `app.graph._nodes.length === 66` (TRELLIS template) immediately before queueing.
