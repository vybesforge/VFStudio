#!/usr/bin/env python3
"""vse_build.py — headless Blender VSE assembler (Blender 5.x API; verified on 5.2.3).

Run (always through the wrapper, never the bare binary):

    ~/media-stack/bin/blender -b -P ~/media-stack/tools/video/vse_build.py -- edit.json out.mp4

Edit list (JSON) — every key except "timeline" is optional:

{
  "output": {"width": 1280, "height": 720, "fps": 30, "quality": "MEDIUM"},
  "timeline": [                                   # played back to back on the picture track
    {"type": "clip",  "path": "a.mp4", "in": 1.0, "out": 4.0, "volume": 1.0, "mute": false,
     "transition": {"type": "cross", "duration": 0.5}},   # crossfade INTO the next item
    {"type": "image", "path": "still.png", "duration": 2.0},
    {"type": "color", "color": [0, 0, 0], "duration": 1.0}
  ],
  "audio": [                                      # extra audio tracks (music, voice-over)
    {"path": "music.wav", "start": 0.0, "volume": 0.3, "fade_in": 1.0, "fade_out": 2.0,
     "in": 0.0, "duration": null}
  ],
  "titles": [                                     # text strips composited over everything
    {"text": "Hello", "start": 0.0, "duration": 3.0, "size": 90, "position": "center",
     "color": [1, 1, 1, 1], "box": true, "box_color": [0, 0, 0, 0.6], "fade": 0.5}
  ]
}

Paths are resolved relative to the JSON file. Times are seconds. "position" is one of
top | center | bottom. "quality" is Blender's constant_rate_factor: LOSSLESS | PERC_LOSSLESS |
HIGH | MEDIUM | LOW | VERYLOW | LOWEST.  Clips whose fps differs from output fps are
pre-converted with ffmpeg into <out>_vse_cache/ so their timing stays correct.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import bpy

FFMPEG = str(Path.home() / ".hermes/tools/ffmpeg-9.0.1-darwin-arm64/ffmpeg")
if not os.path.exists(FFMPEG):
    FFMPEG = shutil.which("ffmpeg") or "ffmpeg"


def log(*a):
    print("[vse_build]", *a, flush=True)


def die(msg):
    log("ERROR:", msg)
    sys.exit(1)


# ----------------------------------------------------------------- strip helpers (5.x names)

def set_duration(strip, frames):
    """Final (visible) length of a strip in frames."""
    if hasattr(strip, "duration"):
        strip.duration = int(frames)
    else:  # <5.2 fallback
        strip.frame_final_duration = int(frames)


def set_in_offset(strip, frames):
    """Trim the first N source frames (left handle offset)."""
    if hasattr(strip, "left_handle_offset"):
        strip.left_handle_offset = int(frames)
    else:
        strip.frame_offset_start = int(frames)


def final_start(strip):
    return strip.left_handle if hasattr(strip, "left_handle") else strip.frame_final_start


def final_end(strip):
    return strip.right_handle if hasattr(strip, "right_handle") else strip.frame_final_end


def keyframe(strip, path, value, frame):
    setattr(strip, path, value)
    strip.keyframe_insert(data_path=path, frame=frame)


# ----------------------------------------------------------------- media probing via ffmpeg

def probe_fps(path):
    import re
    r = subprocess.run([FFMPEG, "-hide_banner", "-i", str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    m = re.search(r"([\d.]+) fps", r.stderr)
    return float(m.group(1)) if m else None


def conform_clip(path, fps, cache_dir):
    """Re-encode a clip to the scene fps (constant frame rate) so VSE timing is correct."""
    src_fps = probe_fps(path)
    if src_fps is not None and abs(src_fps - fps) < 0.01:
        return path
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_dir / (Path(path).stem + f"_{fps:g}fps.mp4")
    if out.exists() and out.stat().st_mtime >= Path(path).stat().st_mtime:
        return str(out)
    log(f"conforming {Path(path).name}: {src_fps} fps -> {fps} fps")
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", str(path), "-vf", f"fps={fps}", "-fps_mode", "cfr",
           "-c:v", "libx264", "-preset", "fast", "-crf", "16", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(out)]
    log("$", " ".join(cmd))
    subprocess.run(cmd, check=True)
    return str(out)


# ----------------------------------------------------------------- build

def build(edit_path, out_path):
    edit_path = Path(edit_path).resolve()
    out_path = Path(out_path).resolve()
    base = edit_path.parent
    edit = json.loads(edit_path.read_text())

    def rp(p):
        p = Path(os.path.expanduser(p))
        return str(p if p.is_absolute() else (base / p).resolve())

    out_cfg = edit.get("output", {})
    W = int(out_cfg.get("width", 1920))
    H = int(out_cfg.get("height", 1080))
    FPS = float(out_cfg.get("fps", 30))
    quality = out_cfg.get("quality", "MEDIUM")

    def f(sec):  # seconds -> frame count (int)
        return int(round(float(sec) * FPS))

    sc = bpy.context.scene
    sc.render.resolution_x, sc.render.resolution_y = W, H
    sc.render.resolution_percentage = 100
    sc.render.fps = int(round(FPS))
    sc.render.fps_base = sc.render.fps / FPS if FPS else 1.0
    # Keep video colours untouched (no Filmic/AgX tone-mapping on the output).
    try:
        sc.view_settings.view_transform = "Standard"
    except TypeError:
        pass
    try:
        sc.view_settings.look = "None"
    except TypeError:
        pass
    log(f"view_transform={sc.view_settings.view_transform} display={sc.display_settings.display_device}")
    se = sc.sequence_editor_create()
    strips = se.strips
    cache_dir = out_path.parent / (out_path.stem + "_vse_cache")

    # ---- picture track: items back to back, alternating channels 1/2 so crossfades can overlap
    CH_PIC = (1, 2)
    CH_FX = 3
    CH_TITLE = 4
    CH_AUDIO = 6
    cursor = 1  # first frame
    prev = None
    prev_trans = None
    pic_strips = []
    sound_ch = CH_AUDIO
    for i, item in enumerate(edit.get("timeline", [])):
        kind = item.get("type", "clip")
        ch = CH_PIC[i % 2]
        overlap = f(prev_trans["duration"]) if prev_trans else 0
        start = cursor - overlap
        name = f"{kind}_{i:02d}"
        if kind == "clip":
            path = conform_clip(rp(item["path"]), FPS, cache_dir)
            st = strips.new_movie(name=name, filepath=path, channel=ch, frame_start=start, fit_method=item.get("fit", "FIT"))
            src_len = st.duration if hasattr(st, "duration") else st.frame_final_duration
            in_f = f(item.get("in", 0))
            out_f = f(item["out"]) if item.get("out") is not None else src_len
            out_f = min(out_f, src_len)
            if out_f <= in_f:
                die(f"{name}: out ({item.get('out')}) must be after in ({item.get('in', 0)})")
            # frame_start is the position of source frame 0; shift it so the trimmed start lands on `start`
            st.frame_start = start - in_f
            set_in_offset(st, in_f)
            set_duration(st, out_f - in_f)
            if not item.get("mute", False):
                snd = strips.new_sound(name=name + "_audio", filepath=path, channel=sound_ch, frame_start=start - in_f)
                set_in_offset(snd, in_f)
                set_duration(snd, out_f - in_f)
                snd.volume = float(item.get("volume", 1.0))
                sound_ch += 1
        elif kind == "image":
            st = strips.new_image(name=name, filepath=rp(item["path"]), channel=ch, frame_start=start, fit_method=item.get("fit", "FIT"))
            set_duration(st, f(item.get("duration", 3)))
        elif kind == "color":
            st = strips.new_effect(name=name, type="COLOR", channel=ch, frame_start=start, length=f(item.get("duration", 2)))
            st.color = tuple(item.get("color", [0, 0, 0]))[:3]
        else:
            die(f"unknown timeline type {kind!r}")
        st.blend_type = "ALPHA_OVER"
        if prev is not None and prev_trans:
            ttype = prev_trans.get("type", "cross").upper()
            ttype = {"CROSS": "CROSS", "GAMMA_CROSS": "GAMMA_CROSS", "WIPE": "WIPE", "FADE": "CROSS"}.get(ttype, "CROSS")
            fx = strips.new_effect(name=f"trans_{i:02d}", type=ttype, channel=CH_FX, frame_start=start, length=overlap, input1=prev, input2=st)
            log(f"transition {ttype} {prev.name}->{st.name} frames {final_start(fx)}-{final_end(fx)}")
        pic_strips.append(st)
        log(f"{name}: ch{ch} frames {final_start(st)}-{final_end(st)}")
        cursor = final_end(st)
        prev = st
        prev_trans = item.get("transition")
    if not pic_strips:
        die("timeline is empty")
    total_frames = max(final_end(s) for s in pic_strips) - 1

    # ---- fade to/from black at the very ends if requested
    fade_in, fade_out = f(edit.get("fade_in", 0)), f(edit.get("fade_out", 0))
    if fade_in or fade_out:
        blk = strips.new_effect(name="fade_black", type="COLOR", channel=CH_TITLE + 1, frame_start=1, length=total_frames)
        blk.color = (0, 0, 0)
        blk.blend_type = "ALPHA_OVER"
        if fade_in:
            keyframe(blk, "blend_alpha", 1.0, 1)
            keyframe(blk, "blend_alpha", 0.0, 1 + fade_in)
        else:
            keyframe(blk, "blend_alpha", 0.0, 1)
        if fade_out:
            keyframe(blk, "blend_alpha", 0.0, total_frames + 1 - fade_out)
            keyframe(blk, "blend_alpha", 1.0, total_frames + 1)

    # ---- titles
    POS = {"top": (0.5, 0.85, "TOP"), "center": (0.5, 0.5, "CENTER"), "bottom": (0.5, 0.12, "BOTTOM")}
    for i, t in enumerate(edit.get("titles", [])):
        start = 1 + f(t.get("start", 0))
        length = f(t.get("duration", 3))
        ts = strips.new_effect(name=f"title_{i:02d}", type="TEXT", channel=CH_TITLE, frame_start=start, length=length)
        ts.text = t["text"]
        ts.font_size = int(t.get("size", 80))
        x, y, anchor_y = POS.get(t.get("position", "center"), POS["center"])
        if "x" in t:
            x = float(t["x"])
        if "y" in t:
            y = float(t["y"])
        ts.location = (x, y)
        ts.anchor_x = "CENTER"
        ts.anchor_y = anchor_y
        ts.alignment_x = "CENTER"
        ts.wrap_width = float(t.get("wrap", 0.9))
        ts.color = tuple(t.get("color", [1, 1, 1, 1]))
        ts.use_shadow = bool(t.get("shadow", True))
        ts.use_box = bool(t.get("box", False))
        if ts.use_box:
            ts.box_color = tuple(t.get("box_color", [0, 0, 0, 0.6]))
            ts.box_margin = float(t.get("box_margin", 0.02))
        if t.get("font"):
            ts.font = bpy.data.fonts.load(rp(t["font"]))
        ts.blend_type = "ALPHA_OVER"
        fade = f(t.get("fade", 0))
        if fade:
            keyframe(ts, "blend_alpha", 0.0, start)
            keyframe(ts, "blend_alpha", 1.0, start + fade)
            keyframe(ts, "blend_alpha", 1.0, start + length - fade)
            keyframe(ts, "blend_alpha", 0.0, start + length)
        log(f"title_{i:02d}: '{ts.text[:30]}' frames {final_start(ts)}-{final_end(ts)}")

    # ---- extra audio tracks
    for i, a in enumerate(edit.get("audio", [])):
        start = 1 + f(a.get("start", 0))
        in_f = f(a.get("in", 0))
        snd = strips.new_sound(name=f"audio_{i:02d}", filepath=rp(a["path"]), channel=sound_ch, frame_start=start - in_f)
        sound_ch += 1
        if in_f:
            set_in_offset(snd, in_f)
        src_len = (snd.duration if hasattr(snd, "duration") else snd.frame_final_duration)
        length = f(a["duration"]) if a.get("duration") else src_len
        if a.get("trim_to_video", True):
            length = min(length, total_frames + 1 - start)
        set_duration(snd, length)
        vol = float(a.get("volume", 1.0))
        snd.volume = vol
        fi, fo = f(a.get("fade_in", 0)), f(a.get("fade_out", 0))
        if fi:
            keyframe(snd, "volume", 0.0, start)
            keyframe(snd, "volume", vol, start + fi)
        if fo:
            keyframe(snd, "volume", vol, start + length - fo)
            keyframe(snd, "volume", 0.0, start + length)
        log(f"audio_{i:02d}: vol {vol} frames {final_start(snd)}-{final_end(snd)}")

    # ---- render settings
    sc.frame_start = 1
    sc.frame_end = total_frames
    r = sc.render
    r.use_sequencer = True
    if hasattr(r.image_settings, "media_type"):   # Blender 5.x: FFMPEG only appears after media_type=VIDEO
        r.image_settings.media_type = "VIDEO"
    r.image_settings.file_format = "FFMPEG"
    r.image_settings.color_mode = "RGB"
    r.ffmpeg.format = "MPEG4"
    r.ffmpeg.codec = "H264"
    r.ffmpeg.constant_rate_factor = quality
    r.ffmpeg.ffmpeg_preset = "GOOD"
    r.ffmpeg.gopsize = int(FPS)
    r.ffmpeg.audio_codec = "AAC"
    r.ffmpeg.audio_bitrate = 192
    r.ffmpeg.audio_mixrate = 48000
    r.use_file_extension = True
    # Blender appends the frame range to movie filenames; render to a prefix then rename.
    out_path.parent.mkdir(parents=True, exist_ok=True)
    prefix = out_path.parent / (out_path.stem + "_render_")
    r.filepath = str(prefix)
    log(f"render {W}x{H} @ {FPS} fps, {total_frames} frames ({total_frames / FPS:.2f} s) -> {out_path}")
    if edit.get("save_blend"):
        bpy.ops.wm.save_as_mainfile(filepath=str(out_path.with_suffix(".blend")))
    bpy.ops.render.render(animation=True)
    produced = sorted(out_path.parent.glob(prefix.name + "*"), key=lambda p: p.stat().st_mtime)
    if not produced:
        die("render produced no file")
    produced[-1].replace(out_path)
    log(f"DONE {out_path} ({out_path.stat().st_size} bytes)")


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if len(argv) != 2:
        die("usage: blender -b -P vse_build.py -- edit.json out.mp4")
    build(argv[0], argv[1])
