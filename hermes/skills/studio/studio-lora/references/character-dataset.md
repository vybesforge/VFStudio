# Building a character dataset locally (before a LoRA or a 3D asset)

When the user wants one recurring character across images, a LoRA and video, the
dataset comes first and everything downstream inherits its quality. Generate it from a
single identity anchor with Qwen-Image-Edit 2509 + `Qwen-Edit-2509-Multiple-angles`.

## Stage 0 — the two masters

1. **Identity anchor**: the user's own hero photo. Never substitute a text-generated
   portrait for it — the face is the model's prior, not the subject.
2. **Body master**: re-pose the anchor into a full-body A-pose with the editor, then
   SeedVR2-upscale 2× (`gen upscale … --method seedvr2 --scale 2`). Verify with
   `pose_measure.py` (arm angle, hand-tip clearance, margins), not by eye.
3. **Face master**: a **neck-up** crop of the anchor at native resolution, SeedVR2 2×
   (~2.1k px). A full-body master puts ~300 px on the face, which is not enough for a
   head recon or for face-detail training images. The user will ask for this — a
   full-body frame never contains "the whole face" at usable size.

## Stage 1 — the sets (aim for 30–60 images, not 8)

Variety is the point; a LoRA trained on one pose in one outfit learns the outfit.
Cover, in this order:

| set | contents | notes |
|---|---|---|
| orbit | front, ¾ L/R, both profiles, rear, rear-¾ | azimuth obeys the Multiple-angles LoRA |
| extremes | floor-level worm's-eye, 45° high, straight overhead, knee-height close | needs *camera-physical* wording — see below |
| poses | relaxed, hands on hips, arms crossed, walking to/away, lunge, crouch, seated, lying, reach overhead, lean, jump, quad stretch, hands behind head | the body must actually change, not just the camera |
| outfits | sundress + straw hat, sportswear, swimwear, denim jacket, evening dress, hoodie, overalls, leather jacket, linen shirt, jump suit… | invent freely; keep it non-explicit |
| expressions | neutral, closed-mouth smile, big laugh, serious, surprised, angry, eyes closed, wink, looking away, biting lip | user asks for these by default; treat as part of the standard set |

## Stage 2 — prompt rules that make the batches usable

- **Restate framing in every prompt.** Angle prompts silently re-crop otherwise:
  "Full body shot: the entire figure from the top of her bun to her bare feet is fully
  inside the frame with clear margin" … and for detail shots "close-up detail shot,
  that body part fills the frame".
- **Repeat the identity as positives**: skin tone, hair colour + style, build, marks,
  jewellery, current outfit. Image conditioning alone still drifts.
- **Name the camera, not the angle**, for elevation: "very low camera placed on the
  floor at her feet, tilted up forty five degrees … feet largest in the frame …
  underside of her chin" works; "low angle" returns eye level. Same for
  "camera mounted on the ceiling pointing straight down".
- **Add side margin** when arms are out: fingertips otherwise land within tens of
  pixels of the edge and clip.
- **Captions name the wardrobe and the pose**, e.g. `pepper, cream summer sundress
  with a straw sun hat, walking toward camera`. The trigger token must bind identity,
  not a costume.

## Stage 3 — assemble

```python
# train/datasets/<name>/<job>.png  +  <job>.txt
# resize to 1024 long side, RGB; caption = "<trigger>, <outfit/pose/camera>"
im.resize((int(w*s), int(h*s)), Image.LANCZOS).save(dst)
(dst.with_suffix('.txt')).write_text(f"{trigger}, {caption}\n")
```

Keep a manifest (`{name: {file, caption}}`) written after every finished job — it is
the dataset list AND the resume state.

## Cost and robustness

- 4-step Lightning + Multiple-angles at 832×1248 ≈ **150 s/image** on M3 Max 64 GB, so
  30 images ≈ 75 min and 60 ≈ 2.5 h. Plan for it, do not babysit one long loop.
- Make the batch resumable (skip existing outputs) and retry each API call with
  backoff — a ComfyUI restart mid-batch otherwise loses every remaining image.
- The face master is worth more than 20 extra angles: identity lives in the face crop,
  the recon/quality ceiling lives in the A-pose master.

## Step budget and master choice (measured)

| job | setting | wall time |
|---|---|---|
| A-pose / angle / pose / outfit view | 4-step Lightning LoRA, 832×1248 | ~150 s |
| same prompt, full quality | 20 steps, cfg 2.5 | **~21 min** (57-68 s/step) |
| SeedVR2 2× upscale of a master | 832×1248 → 1664×2496, or 1024×1408 → 2048×2816 | 65-100 s |
| dataset assembly (resize + captions) | CPU only | seconds |

- **Iterate at 4 steps, promote only the winner to 20.** A 20-step re-run does not
  reproduce the 4-step composition — the sampling trajectory differs — so pick the
  seed by eye at 4 steps and treat the 20-step pass as a *quality* pass for that one
  image, expecting a slightly different pose.
- **Run expressions against the FACE master at a portrait aspect** (~1024²), not the
  body master: a face that is 300 px in the full body has no mouth pixels to animate,
  and expression prompts then change the head shape instead of the expression.
- **Do not spend angle-batch slots on head/hand/feet close-ups** when a face master
  exists — the detail crops generated from the body master are softer than the master
  itself and add near-duplicates the user is paying GPU time for.

## Expect the arms to come back wide (and measure, don't argue)

Every A-pose attempt this stack produced landed at **54-64° off vertical**, never the
30-45° the prompt asks for — the editor carries a wide-T prior and re-rolling seven
seeds does not beat it. 55°-ish is still a usable A-pose (clear triangular gaps at the
waist, no fused armpits), so accept the measured best rather than burning 20-step runs.
Decide with `pose_measure.py` (`arm_angle_left_deg` / `arm_angle_right_deg`,
`hand_tip_inside_px`), never with a VLM's angle estimate — on the same image it said
both "45 degrees" and "almost horizontal".
