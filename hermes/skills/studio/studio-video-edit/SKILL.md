---
name: studio-video-edit
description: "Use when editing video locally: vid CLI, Blender VSE, SRT."
version: 1.0.0
author: Jimmy
license: Apache-2.0
platforms: [macos]
metadata:
  hermes:
    tags: [video, ffmpeg, blender, vse, subtitles, whisper, kokoro, local-inference, studio]
    category: studio
---

# Studio video edit (fully local)

> **Save deliverables under `~/media-stack/output/video/`** — that is where the VF Studio panel (http://127.0.0.1:8787) looks; files elsewhere never show up or preview there. Any subfolder inside is fine.

Three tools under `/Users/dcruse/media-stack/tools/video/` cover trimming, joining, captioning,
audio, GIFs, frame I/O, loudness, multi-clip assembly with crossfades/titles (Blender VSE), and
speech-to-SRT (local Whisper). Nothing calls a cloud API; inference is the mlx-audio server on
`127.0.0.1:8000`. Every `vid` subcommand prints the exact ffmpeg command it ran (line starting
with `$ `) on stderr, then `wrote <file>` on stdout.

## When to use

- Cut / join / resize / speed-change / caption / add music to an mp4.
- Turn frames into a video or a video into frames or a GIF.
- Assemble several clips + stills + titles + music into one mp4 with crossfades.
- Make an `.srt` from speech in a video, then burn it in.
- Normalise loudness to -16 LUFS before publishing.
- Don't use for: image generation (ComfyUI, see `local-media-stack`), 3D (Blender scene work).

## Prerequisites (exact paths — all already installed, check only)

```bash
test -x /Users/dcruse/media-stack/tools/video/vid && echo vid-ok
test -x /Users/dcruse/.hermes/tools/ffmpeg-9.0.1-darwin-arm64/ffmpeg && echo ffmpeg-ok
test -x /Users/dcruse/media-stack/bin/blender && echo blender-ok       # Blender 5.2.3 wrapper; NEVER call the .app binary directly
curl -s -m 3 http://127.0.0.1:8000/v1/models >/dev/null && echo stt-server-ok   # needed only for transcribe
```

- `vid` runs on `/Users/dcruse/media-stack/tools/.venv/bin/python` (3.12) via its shebang. No activation needed.
- There is NO `ffprobe` on this machine; `vid info` parses `ffmpeg -i` instead. Do not call `ffprobe`.
- If `stt-server-ok` is missing, start it (takes ~10 s; first STT request then takes 20–45 s cold):
  `cd /Users/dcruse/media-stack && ./bin/stack start audio` — or directly
  `PATH=/Users/dcruse/.hermes/tools/ffmpeg-9.0.1-darwin-arm64:$PATH /Users/dcruse/media-stack/audio/.venv/bin/python -m mlx_audio.server --host 127.0.0.1 --port 8000`
  (background it with `terminal(background=true)`).
- Put scratch output under `/Users/dcruse/media-stack/scratch/video-test/`.
- Do not touch ComfyUI (`:8188`) — it is unrelated to this skill.

Set once per shell so recipes are copy-pasteable:

```bash
V=/Users/dcruse/media-stack/tools/video/vid
```

## Recipes (vid)

Every recipe: run it via `terminal(command=...)`, then confirm stdout ends with `wrote <output>`.
Time arguments accept seconds (`2.5`) or `HH:MM:SS.ms`.

**Inspect a file** → JSON with duration, size, video w/h/fps/codec, audio codec/rate/channels.
```bash
$V info in.mp4
```
Expect: `"duration_s": 6.0`, a `"type": "video"` entry and (if present) a `"type": "audio"` entry.

**Trim (frame-accurate re-encode)** → clip from 1.0 s lasting 2 s. Use `--end 4` instead of `--duration` for an end time.
```bash
$V trim in.mp4 out.mp4 --start 1 --duration 2
```
Add `--copy` for instant keyframe-snapped cuts (imprecise by up to one GOP). Verify: `$V info out.mp4 | grep duration`.

**Concat (any mix of sizes/fps; re-encodes)** → last argument is the OUTPUT.
```bash
$V concat a.mp4 b.mp4 c.mp4 joined.mp4 --width 1920 --height 1080 --fps 30
```
Clips are letterboxed to the given size. Audio is required on all or none. Use `--copy` only when all inputs came from the same encode settings.

**Resize / letterbox / crop**
```bash
$V resize in.mp4 out.mp4 --width 1080 --height 1080 --mode fit     # fit=pad, crop=center-crop, stretch
$V resize in.mp4 out.mp4 --width 1280                              # keep aspect
```

**Speed** → 2.0 = twice as fast, 0.25 = quarter speed; audio pitch is preserved.
```bash
$V speed in.mp4 out.mp4 --factor 2
```
Expect duration ≈ input/factor (`6 s → 3.07 s` measured).

**Text overlay / title** → positions: top, center, bottom, top-left, top-right, bottom-left, bottom-right.
```bash
$V overlay-text in.mp4 out.mp4 --text "Hello: it's 100% fine" --position top --size 56 --box --start 1 --end 4
```
Any characters are safe in `--text` (written to a temp file, `expansion=none`). Omit `--start/--end` to show for the whole clip. `--font /path/to/font.ttf` to choose a font.

**Add audio**
```bash
$V add-audio in.mp4 music.wav out.mp4 --mode replace                      # drop original audio
$V add-audio in.mp4 music.wav out.mp4 --mode mix  --music-volume 0.3      # bed under original
$V add-audio in.mp4 music.wav out.mp4 --mode duck --music-volume 0.8      # music auto-dips when the voice speaks
```
Add `--loop` when the music is shorter than the video. Output always has stereo 48 kHz AAC and ends with the video (`-shortest`). Tune ducking with `--duck-threshold 0.05 --duck-ratio 8 --duck-release 400`.

**Extract audio** → format from extension (.wav .mp3 .m4a .flac). For STT use 16 kHz mono:
```bash
$V extract-audio in.mp4 voice.wav --mono --rate 16000
```

**GIF**
```bash
$V to-gif in.mp4 out.gif --start 1 --duration 2 --fps 12 --width 480
```
Expect a palette-optimised GIF; 2 s @ 320 px was 140 KB.

**Frames out / frames in**
```bash
$V frames in.mp4 frames_dir --fps 2 --format png            # -> frames_dir/frame_00001.png ...; prints "wrote N frames"
$V from-frames 'frames_dir/frame_%05d.png' out.mp4 --fps 2  # printf pattern
$V from-frames 'frames_dir/*.png' out.mp4 --fps 24 --glob --audio music.wav   # glob pattern (+ optional audio)
```
Quote the pattern. Odd dimensions are auto-rounded to even.

**Burn subtitles**
```bash
$V subtitles in.mp4 captions.srt out.mp4 --size 24 --margin 30
```
Argument order is input, srt, output. `--font Helvetica` takes a font NAME, not a path.

**Thumbnail**
```bash
$V thumbnail in.mp4 thumb.jpg --at 2 --width 640      # frame at 2 s
$V thumbnail in.mp4 thumb.png                          # auto-picked representative frame, full size
```

**Normalise loudness (EBU R128)** → default -16 LUFS, -1.5 dBTP. Works on video (audio re-encoded, video copied) and audio files.
```bash
$V normalize-loudness in.mp4 out.mp4
$V normalize-loudness voice.wav voice_norm.wav --two-pass    # prints "measured: input_i=... LUFS" then applies exact gain
```
Verify: `/Users/dcruse/.hermes/tools/ffmpeg-9.0.1-darwin-arm64/ffmpeg -hide_banner -nostats -i out.mp4 -af loudnorm=print_format=summary -f null - 2>&1 | grep 'Input Integrated'` → `-16.0 LUFS` (±1).

## Recipe: multi-clip assembly with Blender VSE

Write an edit list JSON (times in seconds, paths absolute or relative to the JSON file, `~` allowed), then:

```bash
/Users/dcruse/media-stack/bin/blender -b -P /Users/dcruse/media-stack/tools/video/vse_build.py -- /path/to/edit.json /ABSOLUTE/path/out.mp4
```

Start by copying the shipped example and editing paths:
```bash
cp /Users/dcruse/media-stack/tools/video/edit.example.json /Users/dcruse/media-stack/scratch/video-test/edit.json
```

Schema (all keys except `timeline` optional):
```json
{
  "output": {"width": 1280, "height": 720, "fps": 30, "quality": "MEDIUM"},
  "fade_in": 0.5, "fade_out": 0.5,
  "timeline": [
    {"type": "clip",  "path": "a.mp4", "in": 1.0, "out": 4.0, "volume": 1.0, "mute": false,
     "transition": {"type": "cross", "duration": 0.5}},
    {"type": "image", "path": "still.png", "duration": 2.0},
    {"type": "color", "color": [0, 0, 0], "duration": 1.0}
  ],
  "audio":  [{"path": "music.wav", "start": 0.0, "volume": 0.4, "fade_in": 0.5, "fade_out": 1.5}],
  "titles": [{"text": "My title", "start": 0.3, "duration": 2.5, "size": 96, "position": "center", "box": true, "fade": 0.4},
             {"text": "lower third", "start": 3.0, "duration": 3.0, "size": 48, "position": "bottom", "color": [1, 0.9, 0.3, 1]}]
}
```
- `timeline` items play back to back; `transition` on an item crossfades INTO the next one (types: cross, gamma_cross, wipe).
- `quality`: LOSSLESS | PERC_LOSSLESS | HIGH | MEDIUM | LOW | VERYLOW | LOWEST.
- Clip fps ≠ output fps is handled automatically (ffmpeg conform into `<out>_vse_cache/`).
- `"save_blend": true` at top level also writes `out.blend` for opening in the Blender UI.

Expected stdout (grep `vse_build`):
```
[vse_build] view_transform=Standard display=sRGB
[vse_build] clip_00: ch1 frames 1-91
[vse_build] transition CROSS clip_00->clip_01 frames 76-91
...
[vse_build] render 1280x720 @ 30.0 fps, 225 frames (7.50 s) -> /.../out.mp4
[vse_build] DONE /.../out.mp4 (1482257 bytes)
```
The example (4 items, 2 crossfades, 2 titles, music) rendered in 2.4 s wall time.

## Recipe: speech → .srt → burned captions (local Whisper)

```bash
/Users/dcruse/media-stack/tools/video/transcribe_srt.py talk.mp4 talk.srt
$V subtitles talk.mp4 talk.srt talk_subs.mp4
```
Expected stdout: `response_format=srt did not return SRT; falling back to verbose_json`, `built SRT from N segments`, `wrote talk.srt (M captions)`. Options: `--language en`, `--max-chars 42` (line wrap), `--max-dur 6`, `--model mlx-community/whisper-large-v3-turbo-asr-fp16` (default).

To make a spoken test clip locally (Kokoro TTS on the same server):
```bash
curl -s -m 300 http://127.0.0.1:8000/v1/audio/speech -H 'Content-Type: application/json' \
  -d '{"model":"mlx-community/Kokoro-82M-bf16","voice":"af_heart","input":"Hello from the studio.","response_format":"wav"}' -o tts.wav
$V add-audio in.mp4 tts.wav talk.mp4 --mode replace
```

## Verify

1. `vid` ops: stdout ends in `wrote <file>`; then `$V info <file>` shows the expected `duration_s`, `width`/`height`, and an audio stream when one was expected.
2. Visual check of overlays/subtitles: `ffmpeg -y -ss 2 -i out.mp4 -frames:v 1 f.png` then `vision_analyze` on `f.png` and ask "quote the on-screen text".
3. VSE: the log line `[vse_build] DONE ...` exists AND `$V info out.mp4` reports the planned duration (frames / fps).
4. SRT: `cat out.srt` shows `N` / `HH:MM:SS,mmm --> HH:MM:SS,mmm` / text blocks; timestamps increase.
5. Loudness: the `Input Integrated` check above reads within ±1 LU of the target.

## Pitfalls (all hit while building this)

- **No `ffprobe` in the bundled ffmpeg dir** and a network download of one was blocked by approval. `vid info` parses `ffmpeg -i`; never write recipes that call `ffprobe`.
- **ffmpeg 9 removed `-vsync`.** Use `-fps_mode cfr`. Scripts copied from older blogs fail with `Option not found`.
- **drawtext `%` → "Stray %"** and `\%` does not fix it because the filtergraph parser eats one backslash. `vid overlay-text` sidesteps this with `textfile=` + `expansion=none`; keep that approach for any hand-written drawtext.
- **Blender 5.x API differs from 3.x/4.x** (verified on 5.2.3): `scene.sequence_editor.strips` (not `.sequences`), `new_effect(name, type, channel, frame_start, length, input1, input2)` (no `frame_end`), `strip.duration` / `strip.left_handle_offset` (the `frame_final_duration` / `frame_offset_start` names are deprecated for 6.0), and **`image_settings.media_type = "VIDEO"` must be set before `file_format = "FFMPEG"`** or the enum rejects FFMPEG.
- **VSE does not retime clips whose fps differs from the scene** — a 25 fps clip in a 30 fps scene plays 20 % too fast. `vse_build.py` pre-conforms such clips with ffmpeg; if you bypass it, convert first (`$V resize in.mp4 out.mp4 --width <w> --fps 30`).
- **Blender appends the frame range to movie filenames** (`out_0001-0225.mp4`). `vse_build.py` renders to a prefix and renames; expect only `out.mp4` afterwards.
- **Blender output path must be absolute.** Relative paths fail at save time.
- **`view_transform` enum lists only `NONE` in headless mode** but assigning `"Standard"` still works; leave the default (AgX) and video colours shift.
- **`fit_method="FIT"` pillarboxes stills** — an 800×600 image in a 1280×720 frame has black side bars; frame-average colour checks will read darker than the source. That is letterboxing, not a colour bug.
- **mlx-audio ignores `response_format=srt`** and returns verbose JSON with `segments`; `transcribe_srt.py` detects this and builds the SRT itself. Do not hand-parse the `srt` response.
- **`vid add-audio` uses `-shortest`:** a 10 s voice track on a 6 s video is cut at 6 s. Extend the video first (concat/image) if the speech must finish.
- **Argument order:** `vid subtitles INPUT SRT OUTPUT` and `vid concat IN1 IN2 ... OUTPUT` — the output is last.
