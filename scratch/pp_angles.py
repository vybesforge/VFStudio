"""Generate a multi-angle dataset of one subject from a single A-pose master image.

Qwen-Image-Edit 2509 (Q4 GGUF) + `Qwen-Edit-2509-Multiple-angles` LoRA, which is the
camera-angle tool for this model family. Each job re-renders the SAME woman from a new
camera position; identity comes from the reference conditioning, not from the prompt,
so the wording only has to describe the camera and any framing change.

Resumable: skips jobs whose output already exists, so a long batch can be restarted.
Every finished job is appended to <outdir>/manifest.json with its caption, which is what
the LoRA dataset builder reads.

  python pp_angles.py --master output/image/pepper_apose_MASTER.png \
      --outdir output/image/pepper_angles [--fast] [--only name1,name2]
"""
import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image

HOST = "http://127.0.0.1:8188"
COMFY = Path("/Users/dcruse/media-stack/ComfyUI")
UNET = "Qwen-Image-Edit-2509-Q4_K_M.gguf"
CLIP = "qwen_2.5_vl_7b_fp8_scaled.safetensors"
VAE = "qwen_image_vae.safetensors"
MULTI_LORA = "Qwen-Edit-2509-Multiple-angles.safetensors"
LIGHTNING = "Qwen-Image-Edit-2509-Lightning-4steps-V1.0-bf16.safetensors"

IDENT = (
    "Same woman, unchanged identity: warm medium tan olive skin, athletic toned build "
    "with defined abs, dark brown hair in a high messy top-knot bun, dark brown eyes, "
    "thick dark eyebrows, small mole on her left cheek, silver navel piercing, tight "
    "olive-green ribbed short-sleeve crop top, mid-rise blue denim jeans, barefoot."
)

# (name, camera instruction, caption fragment for LoRA training)
ANGLES = [
    ("front",        "front view, the camera directly in front of her at chest height",
     "front view, standing A-pose, plain grey studio background"),
    ("q34_left",     "three-quarter view from her front left, camera at chest height",
     "three-quarter view from her left, standing A-pose, grey background"),
    ("left",         "left profile view, camera ninety degrees to her left side",
     "left side profile view, standing A-pose, grey background"),
    ("rear_left",    "rear three-quarter view from her back left",
     "rear three-quarter view, grey background"),
    ("back",         "rear view from directly behind her, back of her head visible",
     "back view, standing A-pose, grey background"),
    ("rear_right",   "rear three-quarter view from her back right",
     "rear three-quarter view from the right, grey background"),
    ("right",        "right profile view, camera ninety degrees to her right side",
     "right side profile view, standing A-pose, grey background"),
    ("q34_right",    "three-quarter view from her front right, camera at chest height",
     "three-quarter view from her right, standing A-pose, grey background"),
    ("high_front",   "high angle view from above her, camera raised and looking down at thirty five degrees, front of her body visible",
     "high angle front view looking down, grey background"),
    ("high_left",    "high angle view from above and to her left, looking down at thirty five degrees",
     "high angle left view looking down, grey background"),
    ("high_back",    "high angle from above and behind her, looking down at thirty five degrees",
     "high angle back view looking down, grey background"),
    ("high_right",   "high angle from above and to her right, looking down at thirty five degrees",
     "high angle right view looking down, grey background"),
    ("low_front",    "low angle view from near floor level looking up at her, thirty five degrees below chest height",
     "low angle front view looking up, grey background"),
    ("low_left",     "low angle from floor level to her left, looking up",
     "low angle left view looking up, grey background"),
    ("low_back",     "low angle from floor level behind her, looking up",
     "low angle back view looking up, grey background"),
    ("low_right",    "low angle from floor level to her right, looking up",
     "low angle right view looking up, grey background"),
    ("top_down",     "top-down view straight down from above her head, the floor visible around her feet",
     "top-down view from directly above, grey background"),
    ("bottom_up",    "bottom-up view from directly below, looking straight up past her feet and legs",
     "bottom-up view from directly below, grey background"),
    ("head_front",   "close-up portrait of her face and head, front view, filling the frame",
     "close-up face portrait, front view"),
    ("head_q34",     "close-up portrait of her face at three-quarter angle, filling the frame",
     "close-up face portrait, three-quarter view"),
    ("head_left",    "close-up portrait of her head in left profile, filling the frame",
     "close-up face portrait, left profile"),
    ("head_right",   "close-up portrait of her head in right profile, filling the frame",
     "close-up face portrait, right profile"),
    ("head_back",    "close-up of the back of her head and bun, rear view, filling the frame",
     "close-up of the back of her head and hair bun"),
    ("head_top",     "close-up of the top of her head and hair bun seen from above",
     "close-up top of head and hair bun from above"),
    ("torso_front",  "medium close-up of her torso and arms, front view",
     "medium close-up of torso and arms, front view"),
    ("torso_q34",    "medium close-up of her torso and arms at three-quarter view",
     "medium close-up of torso and arms, three-quarter view"),
    ("hands_front",  "close-up of both hands with fingers spread, palms facing the camera",
     "close-up of both hands, fingers spread, palms facing camera"),
    ("hands_side",   "close-up of her hand in side profile, fingers spread",
     "close-up of one hand in side profile, fingers spread"),
    ("feet_front",   "close-up of her bare feet from the front, toes visible",
     "close-up of bare feet, front view"),
    ("feet_side",    "close-up of her bare feet from the side, arch and heel visible",
     "close-up of bare feet, side view"),
    ("waist_detail", "close-up of her waist, abdominal muscles and navel piercing",
     "close-up of waist and abdomen with navel piercing"),
    ("full_far",     "full body view from further away so the whole figure is small in the frame with lots of background around her",
     "full body wide shot, standing A-pose, grey background"),
]


# Pose / position / perspective variety — camera position AND body pose both change.
# The orbit list above only moves the camera around a standing A-pose; a LoRA dataset
# needs the body doing different things, seen from extremes (ground level, overhead).
POSES = [
    ("relaxed_front",
     "She stands relaxed with her weight on one hip, arms hanging naturally at her sides, "
     "hands slightly turned in, camera at chest height directly in front of her",
     "relaxed standing pose, weight on one hip, front view"),
    ("hands_on_hips",
     "She stands with both hands resting on her hips, elbows out, chin slightly raised, "
     "camera at chest height at a three-quarter angle",
     "hands on hips, three-quarter view"),
    ("arms_crossed",
     "She stands with her arms folded across her chest, shoulders square to the camera",
     "arms crossed over chest, front view"),
    ("walking_to_camera",
     "She walks toward the camera in mid-stride, one foot forward, arms swinging, "
     "camera at chest height in front of her",
     "walking toward camera, mid stride"),
    ("walking_away",
     "She walks away from the camera in mid-stride, seen from behind, "
     "camera at chest height behind her",
     "walking away from camera, rear view"),
    ("lunge_side",
     "She holds a deep side lunge, one leg bent and the other straight, hands on her front thigh, "
     "camera at chest height in front of her",
     "side lunge athletic pose, front view"),
    ("crouch_low",
     "She crouches down with one knee near the floor and the other leg bent, one hand on the floor, "
     "camera low near the floor looking slightly up at her",
     "crouching low pose, low camera looking up"),
    ("floor_seated",
     "She sits on the floor with her knees bent in front of her and her hands resting behind her, "
     "camera at chest height looking slightly down",
     "seated on the floor, knees bent, looking slightly down"),
    ("lying_top_down",
     "She lies on her back on the floor with her arms out to the sides and her knees bent, "
     "camera directly above her looking straight down",
     "lying on floor, top-down view from directly above"),
    ("reach_up",
     "She reaches both arms straight up overhead in a long stretch, standing tall, "
     "camera at chest height in front of her",
     "stretching both arms overhead, front view"),
    ("lean_back",
     "She leans back and stretches one arm across her chest, weight on her back foot, "
     "camera at chest height at a three-quarter angle",
     "leaning back, arm stretched across chest, three-quarter view"),
    ("jump_low",
     "She jumps straight up with her knees tucked slightly and her arms out, frozen mid-air, "
     "camera near the floor looking up at her",
     "jumping mid-air, low camera looking up"),
    ("feet_level_up",
     "She stands tall while the camera sits on the floor at her feet and looks straight up the "
     "length of her body, her feet largest in the foreground and her head high above, "
     "strong foreshortening",
     "camera on the floor at her feet looking up the length of her body"),
    ("overhead",
     "She stands with her arms out while the camera is directly above her head pointing straight "
     "down, the floor visible around her",
     "top-down overhead view looking straight down at her"),
    ("run_at_camera",
     "She runs toward the camera at full stride, low camera near the floor in front of her",
     "running at the camera, low angle"),
    ("stretch_quad",
     "She balances on one leg and holds her other foot behind her in a quad stretch, "
     "camera at chest height from her side",
     "quad stretch standing on one leg, side view"),
    ("hands_behind_head",
     "She stands with both hands clasped behind her head, elbows wide, abs engaged, "
     "camera at chest height in front of her",
     "hands behind head, elbows wide, front view"),
    ("profile_walk_past",
     "She walks across the frame past the camera in profile, mid-stride, "
     "camera at chest height at ninety degrees to her side",
     "walking in profile past the camera, side view"),
]


# Outfit / styling variety. Same person, same face — only wardrobe, pose and camera
# change. Captions name the outfit so the trigger token binds to the identity and not
# to the clothes.
OUTFITS = [
    ("bikini_front",
     "She wears a simple black two-piece swimsuit with her arms relaxed at her sides, "
     "camera at chest height directly in front of her",
     "black two-piece swimsuit, standing, front view"),
    ("sports_bra_hips",
     "She wears a charcoal sports bra and matching high-waist leggings, both hands on her hips, "
     "camera at chest height at a three-quarter angle",
     "charcoal sports bra and high-waist leggings, hands on hips, three-quarter view"),
    ("sundress_hat_walk",
     "She wears a light cream summer sundress and a wide-brim straw sun hat, walking toward the "
     "camera in mid-stride, camera at chest height",
     "cream summer sundress with a straw sun hat, walking toward camera"),
    ("denim_jacket",
     "She wears a cropped denim jacket open over a white t-shirt with high-waist jeans, "
     "arms folded loosely, camera at chest height in front of her",
     "cropped denim jacket over white t-shirt and jeans, arms folded, front view"),
    ("evening_black",
     "She wears a fitted sleeveless black evening dress and heels, one hand relaxed at her side, "
     "camera at chest height at a three-quarter angle",
     "sleeveless black evening dress and heels, three-quarter view"),
    ("hoodie_shorts",
     "She wears an oversized pale grey hoodie with the sleeves pushed up and short shorts, "
     "relaxed stance, camera at chest height in front of her",
     "oversized grey hoodie and short shorts, relaxed stance, front view"),
    ("beach_kaftan_seated",
     "She wears an open white linen kaftan over a swimsuit, sitting on the floor with her knees "
     "to one side and her hands behind her, camera slightly above her looking down",
     "white linen kaftan over swimsuit, seated on floor, slightly high camera"),
    ("bucket_hat_rear",
     "She wears a bucket hat, a fitted crop top and loose jeans, looking back over her shoulder "
     "with her body turned away from the camera",
     "bucket hat, crop top and loose jeans, looking back over shoulder, rear three-quarter view"),
    ("cap_running",
     "She wears a baseball cap backwards, a gym tank top and jogger trousers, running toward the "
     "camera at full stride, low camera near the floor in front of her",
     "baseball cap, gym tank and joggers, running at the camera, low angle"),
    ("cropped_hoodie_reach",
     "She wears a cropped grey hoodie and bike shorts, reaching both arms overhead in a stretch, "
     "camera at chest height in front of her",
     "cropped hoodie and bike shorts, reaching overhead, front view"),
    ("overalls_tee",
     "She wears blue denim overalls over a plain white t-shirt, hands pushed into the front pockets, "
     "camera at chest height in front of her",
     "denim overalls over white t-shirt, hands in pockets, front view"),
    ("leather_jacket_low",
     "She wears a black leather biker jacket over a plain top and dark jeans, standing with her "
     "weight on one hip, camera low near the floor looking up at her",
     "black leather biker jacket and dark jeans, low camera looking up"),
    ("linen_shirt_overhead",
     "She wears an oversized white linen shirt open over a dark swim top and shorts, looking up at "
     "the camera directly above her, the floor visible around her",
     "oversized white linen shirt and swim top, top-down overhead view"),
    ("sunhat_long_dress",
     "She wears a long pale yellow summer dress with a broad sun hat, walking across the frame in "
     "profile, camera at chest height at ninety degrees to her side",
     "long pale yellow dress and broad sun hat, walking in profile, side view"),
    ("tank_jump",
     "She wears a light grey tank top and black shorts, jumping straight up with her arms out, "
     "frozen mid-air, camera near the floor looking up",
     "grey tank top and black shorts, jumping mid-air, low camera"),
    ("sweater_jeans_seated_floor",
     "She wears an oversized knit sweater and jeans, sitting cross-legged on the floor looking "
     "straight at the camera, camera at her eye level",
     "oversized knit sweater and jeans, sitting cross-legged on floor, eye level"),
]


# Extreme camera positions. Plain "low angle" was ignored by the editor — it kept
# returning eye level — but naming the physical camera and the foreshortening does work
# (verified: feet loom huge, soles visible, underside of the chin). Keep this wording.
EXTREMES = [
    ("floor_front",
     "Very low camera placed on the floor at her feet, tilted up forty five degrees so the "
     "shot looks up at her from below. Her feet are the largest thing in the frame, her legs "
     "foreshorten dramatically, we see the soles of her feet and the underside of her chin. "
     "Upward perspective distortion, wide lens",
     "extreme low camera at her feet looking up, feet largest in frame"),
    ("floor_back",
     "Very low camera placed on the floor behind her heels, tilted up forty five degrees, "
     "looking up her back from below. Her heels are the largest thing in the frame, her legs "
     "foreshorten upward, the back of her head is small and far away at the top. Upward "
     "perspective distortion, wide lens",
     "extreme low camera behind her feet looking up, rear view"),
    ("floor_side",
     "Very low camera placed on the floor beside her foot, tilted up forty five degrees, "
     "looking up her side from below. Her foot is the largest thing in the frame, her body "
     "rises away into the distance, strong upward perspective distortion",
     "extreme low camera beside her foot looking up, side view"),
    ("high_45",
     "Camera raised high on a boom above and in front of her, tilted down forty five degrees "
     "so the shot looks down at her from above. The floor spreads out behind her feet, her "
     "shoulders and the top of her head are large, her feet are small and far away. Downward "
     "perspective distortion",
     "high camera above her looking down at forty five degrees"),
    ("straight_down",
     "Directly overhead bird's-eye view: the camera is mounted on the ceiling pointing straight "
     "down at her. We see the top of her hair bun, her forehead and nose foreshortened, her "
     "shoulders, the tops of her arms and the floor spread around her feet. Circular top-down "
     "perspective, no horizon line",
     "top-down bird's-eye view straight down, floor around her"),
    ("knee_level_close",
     "Camera at knee height, very close to her, tilted up so her hips and torso dominate the "
     "frame and her head is near the top edge. Shallow depth of field, foreground knees sharp",
     "knee-height close camera tilted up, hips and torso dominant"),
]


# Facial expression set — runs against the FACE master (pepper_face_MASTER.png), not the
# body master, so the mouth/eyes have the pixels to work with.
EXPRESSIONS = [
    ("expr_neutral", "Neutral relaxed face, lips closed, looking straight into the lens",
     "neutral expression, close-up face portrait"),
    ("expr_smile", "Warm closed-lip smile, eyes crinkling slightly at the corners",
     "warm smile, close-up face portrait"),
    ("expr_laugh", "Genuine open laugh, teeth showing, head tipped back a little",
     "laughing, teeth showing, close-up face portrait"),
    ("expr_serious", "Serious intense stare, jaw set, brows slightly lowered",
     "serious intense expression, close-up face portrait"),
    ("expr_surprised", "Surprised expression, eyebrows raised high, lips parted in a small O",
     "surprised expression, eyebrows raised, close-up face portrait"),
    ("expr_angry", "Angry glare, brows drawn down hard, lips pressed together",
     "angry glare, close-up face portrait"),
    ("expr_smirk", "Confident half smirk, one corner of the mouth raised",
     "confident half smirk, close-up face portrait"),
    ("expr_eyes_closed", "Eyes gently closed, calm relaxed face, head slightly tilted",
     "eyes closed, calm relaxed face, close-up face portrait"),
    ("expr_wink", "Playful wink with one eye closed and a small smile",
     "winking with a small smile, close-up face portrait"),
    ("expr_bite_lip", "Playful expression biting her lower lip, eyes looking up at the lens",
     "biting lower lip, close-up face portrait"),
    ("expr_look_away", "Thoughtful expression looking off to her left, not at the camera",
     "looking away thoughtfully, three-quarter face portrait"),
    ("expr_tongue", "Silly playful expression with her tongue slightly out and a grin",
     "playful expression with tongue out, close-up face portrait"),
]


def api(path, payload=None, timeout=3600, tries=6):
    """Tolerate the server restarting mid-run: ComfyUI came back from a blip once and
    killed a whole batch with ConnectionRefused."""
    last = None
    for i in range(tries):
        try:
            data = json.dumps(payload).encode() if payload is not None else None
            req = urllib.request.Request(f"{HOST}{path}", data=data,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
            return json.loads(raw) if raw else {}
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
            last = e
            print(f"[ang] api {path} failed ({e}); retry {i+1}/{tries}", flush=True)
            time.sleep(10 * (i + 1))
    raise last


def wait_idle(give_up=7200, patience=600):
    """Wait for an idle queue, but do not starve: another session can keep ComfyUI busy
    for hours, and ComfyUI is FIFO anyway, so after `patience` seconds submit regardless
    rather than blocking the whole batch."""
    t0 = time.time()
    while time.time() - t0 < give_up:
        try:
            q = api("/queue")
            if not q.get("queue_running") and not q.get("queue_pending"):
                return True
        except Exception:
            pass
        if time.time() - t0 > patience:
            print("[ang] queue busy for %ds, submitting anyway (FIFO)" % patience, flush=True)
            return True
        time.sleep(5)
    return False


def build(image_name, prompt, steps, cfg, seed, w, h, loras):
    wf = {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": UNET}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": CLIP, "type": "qwen_image", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "4": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "5": {"class_type": "FluxKontextImageScale", "inputs": {"image": ["4", 0]}},
        "15": {"class_type": "ImageScale",
               "inputs": {"image": ["5", 0], "upscale_method": "lanczos",
                          "width": w, "height": h, "crop": "disabled"}},
        "6": {"class_type": "TextEncodeQwenImageEditPlus",
              "inputs": {"clip": ["2", 0], "prompt": prompt, "vae": ["3", 0],
                         "image1": ["15", 0]}},
        "7": {"class_type": "TextEncodeQwenImageEditPlus",
              "inputs": {"clip": ["2", 0], "prompt": "", "vae": ["3", 0],
                         "image1": ["15", 0]}},
        "8": {"class_type": "ModelSamplingAuraFlow",
              "inputs": {"model": ["1", 0], "shift": 3.0}},
        "9": {"class_type": "CFGNorm",
              "inputs": {"model": ["8", 0], "strength": 1.0, "pre_cfg": False}},
        "10": {"class_type": "VAEEncode", "inputs": {"pixels": ["15", 0], "vae": ["3", 0]}},
        "11": {"class_type": "KSampler",
               "inputs": {"model": ["9", 0], "positive": ["6", 0], "negative": ["7", 0],
                          "latent_image": ["10", 0], "seed": seed, "steps": steps,
                          "cfg": cfg, "sampler_name": "euler", "scheduler": "simple",
                          "denoise": 1.0}},
        "12": {"class_type": "VAEDecode", "inputs": {"samples": ["11", 0], "vae": ["3", 0]}},
        "13": {"class_type": "SaveImage",
               "inputs": {"images": ["12", 0], "filename_prefix": "pp_angle"}},
    }
    src, n = ["1", 0], 20
    for lname, strength in loras:
        nid = str(n); n += 1
        wf[nid] = {"class_type": "LoraLoaderModelOnly",
                   "inputs": {"model": src, "lora_name": lname, "strength_model": strength}}
        src = [nid, 0]
    wf["8"]["inputs"]["model"] = src
    return wf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--master", default="/Users/dcruse/media-stack/output/image/pepper_apose_MASTER.png")
    ap.add_argument("--outdir", default="/Users/dcruse/media-stack/output/image/pepper_angles")
    ap.add_argument("--size", default="832x1248")
    ap.add_argument("--seed", type=int, default=4242)
    ap.add_argument("--steps", type=int, default=20)
    ap.add_argument("--cfg", type=float, default=2.5)
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--lora-strength", type=float, default=1.0)
    ap.add_argument("--only", default=None)
    ap.add_argument("--set", default="angles", choices=["angles", "poses", "outfits", "extremes", "expressions", "all"],
                    help="angles = camera orbit around the A-pose; poses = body-pose and "
                         "camera-position variety")
    a = ap.parse_args()

    outdir = Path(a.outdir); outdir.mkdir(parents=True, exist_ok=True)
    man_path = outdir / "manifest.json"
    manifest = json.loads(man_path.read_text()) if man_path.exists() else {}
    staged = COMFY / "input" / "pp_angle_master.png"
    Image.open(a.master).convert("RGB").save(staged)
    w, h = (int(v) for v in a.size.lower().split("x"))
    steps, cfg = (4, 1.0) if a.fast else (a.steps, a.cfg)
    loras = [(MULTI_LORA, a.lora_strength)] + ([(LIGHTNING, 1.0)] if a.fast else [])
    print(f"[ang] master={a.master} -> {w}x{h} steps={steps} cfg={cfg} "
          f"loras={[l[0] for l in loras]}", flush=True)

    todo = ANGLES
    if a.set == "poses":
        todo = POSES
    elif a.set == "outfits":
        todo = OUTFITS
    elif a.set == "extremes":
        todo = EXTREMES
    elif a.set == "expressions":
        todo = EXPRESSIONS
    elif a.set == "all":
        todo = ANGLES + POSES + OUTFITS
    if a.only:
        keep = set(a.only.split(","))
        todo = [t for t in todo if t[0] in keep]

    for i, (name, cam, cap) in enumerate(todo, 1):
        dest = outdir / f"pepper_{name}.png"
        if dest.exists():
            print(f"[ang] {i}/{len(todo)} {name}: exists, skip", flush=True)
            manifest[name] = {"file": f"pepper_{name}.png", "caption": cap}
            continue
        if not wait_idle():
            print("[ang] queue never drained, aborting", flush=True)
            break
        close = a.set == "expressions" or name in {"head_front", "head_q34", "head_left", "head_right", "head_back",
                         "head_top", "torso_front", "torso_q34", "hands_front",
                         "hands_side", "feet_front", "feet_side", "waist_detail"}
        framing = ("This is a close-up detail shot, that body part fills the frame."
                   if close else
                   "Full body shot: the entire figure from the top of her bun to her bare "
                   "feet is fully inside the frame with clear margin above her head and "
                   "below her feet.")
        prompt = (f"{cam}. {framing} {IDENT} Plain flat neutral light grey seamless studio "
                  f"background, no props, soft even studio lighting, photorealistic, sharp "
                  f"focus, high detail.")
        t0 = time.time()
        r = api("/prompt", {"prompt": build("pp_angle_master.png", prompt, steps, cfg,
                                           a.seed + i * 37, w, h, loras)})
        pid = r.get("prompt_id")
        if not pid:
            print(f"[ang] {name}: REJECTED {json.dumps(r)[:500]}", flush=True)
            continue
        while True:
            time.sleep(5)
            hz = api(f"/history/{pid}")
            if pid in hz:
                break
            if time.time() - t0 > 2400:
                print(f"[ang] {name}: timeout", flush=True)
                break
        entry = hz.get(pid, {})
        imgs = [im["filename"] for o in entry.get("outputs", {}).values()
                for im in o.get("images", [])]
        if not imgs:
            print(f"[ang] {name}: no image (status={entry.get('status', {}).get('status_str')})",
                  flush=True)
            continue
        Image.open(COMFY / "output" / imgs[0]).save(dest)
        manifest[name] = {"file": f"pepper_{name}.png", "caption": cap}
        man_path.write_text(json.dumps(manifest, indent=1))
        print(f"[ang] {i}/{len(todo)} {name}: {time.time()-t0:.0f}s -> {dest.name}",
              flush=True)
        (outdir / f"pepper_{name}.txt").write_text(f"pepper, {cap}\n")
    print(f"[ang] done, {len(manifest)} entries in {man_path}", flush=True)


if __name__ == "__main__":
    main()
