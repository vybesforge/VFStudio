---
name: studio-voice
description: "Use when you need local TTS, voice cloning, or speech-to-text on this Mac."
version: 1.0.0
author: Jimmy
license: MIT
platforms: [macos]
metadata:
  hermes:
    tags: [studio, voice, tts, stt, voice-cloning, kokoro, qwen3-tts, whisper, mlx-audio, local-inference]
    category: studio
---

# Studio Voice

One CLI, `~/media-stack/tools/voice/voice`, drives the local mlx-audio server
(`http://127.0.0.1:8000`) for text-to-speech (Kokoro), voice cloning
(Qwen3-TTS 1.7B Base), speech-to-text (Whisper large-v3-turbo) and a
speech-cleanup `enhance` pass. Everything runs on this machine. Nothing calls a
cloud API. Do not add any.

## When to use

- Turn text into a spoken wav (`say`).
- Make a new sentence in the voice of an existing recording (`clone`).
- Transcribe a wav/mp3/m4a to text or SRT subtitles (`transcribe`).
- Clean up a speech recording: rumble filter, compression, -16 LUFS (`enhance`).
- Don't use for: music or sound effects (see `local-media-stack`, `stack music`).

## Prerequisites

| Thing | Exact path / value |
|---|---|
| CLI | `~/media-stack/tools/voice/voice` (executable; python in the audio venv) |
| Server | mlx-audio on `http://127.0.0.1:8000` |
| Start server | `~/media-stack/bin/stack start audio` (status: `stack status`, logs: `stack logs audio`) |
| Audio venv | `~/media-stack/audio/.venv` (mlx-audio 0.6.3, python 3.12) |
| Tools venv (enhance) | `~/media-stack/tools/.venv` (pedalboard, soundfile, librosa) |
| ffmpeg (enhance) | `~/.hermes/tools/ffmpeg-9.0.1-darwin-arm64/ffmpeg` |
| TTS model | `mlx-community/Kokoro-82M-bf16` (voice default `af_heart`) |
| Clone model | `mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16` (4.3 GB, in `~/.cache/huggingface/hub`) |
| STT model | `mlx-community/whisper-large-v3-turbo-asr-fp16` |
| Default outputs | `~/media-stack/scratch/voice/<cmd>_<timestamp>.wav` when `--out` is omitted |

Always run this first. It must print `server: up`:

```bash
~/media-stack/tools/voice/voice status
```

If it prints `server: DOWN`, run `~/media-stack/bin/stack start audio`, wait 10 s, run `status` again.

## Recipes

Use `terminal(command=..., timeout=300)` for every command below. Set
`V=~/media-stack/tools/voice/voice` or type the full path.

### 1. Speak text (Kokoro)

```bash
~/media-stack/tools/voice/voice say "Hello from the studio." --voice af_heart --out ~/media-stack/scratch/voice/hello.wav
```
Expected: `/Users/dcruse/media-stack/scratch/voice/hello.wav  (151244 bytes, 0.1s)`.
First call after server start takes 20-45 s (model load); later calls ~0.1 s.
Options: `--speed 1.2` (0.5-2.0). Voice names come from recipe 2.

### 2. List Kokoro voices

```bash
~/media-stack/tools/voice/voice voices
```
Expected: one name per line, e.g. `af_heart af_bella af_nova am_adam am_michael bf_emma bm_george ...`.
Prefix = language+gender: `af`/`am` American female/male, `bf`/`bm` British.

### 3. Clone a voice

You need (a) a reference wav of the voice, 5-15 s of clean speech, and
(b) the exact words spoken in it (`--ref-text`). If you do not have the
transcript, get it with recipe 4 first.

```bash
~/media-stack/tools/voice/voice clone \
  --ref ~/media-stack/scratch/voice-test/ref.wav \
  --ref-text "The quick brown fox jumps over the lazy dog near the riverbank. Every morning, the sun rises over the hills and the birds begin to sing in the tall oak trees." \
  "This new sentence is spoken in the cloned voice." \
  --out ~/media-stack/scratch/voice/cloned.wav
```
Expected: `/Users/dcruse/media-stack/scratch/voice/cloned.wav  (207404 bytes, 1.7s, model mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16)`.
Cold (first call since server start): ~6-10 s. Warm: ~2 s for a sentence.
Server memory grows by ~4.5 GB while the clone model stays loaded.

To make a reference from scratch, use recipe 1 with a 2-sentence text, then
pass that same text as `--ref-text`.

Fallback model (no transcript needed, also installed, 3 GB):
```bash
~/media-stack/tools/voice/voice clone --ref REF.wav "New sentence." --model mlx-community/chatterbox-turbo-fp16 --out /tmp/cb.wav
```
Expected: `/tmp/cb.wav  (113204 bytes, 1.0s, model mlx-community/chatterbox-turbo-fp16)`.
Use Chatterbox only when you have no transcript or Qwen3-TTS fails; Qwen3-TTS is
the default because its transcript conditioning keeps pitch and pacing closer
to the reference (measured below, both are acceptable).

### 4. Transcribe audio (Whisper)

```bash
~/media-stack/tools/voice/voice transcribe ~/media-stack/scratch/voice/cloned.wav
```
Expected: the spoken words as one line, e.g. `This new sentence is spoken in the cloned voice.`

SRT subtitles: add `--srt`. Expected:
```
1
00:00:00,000 --> 00:00:04,100
This new sentence is spoken in the cloned voice.
```
Full JSON with segments: `--json`. Cold ~3 s, warm ~0.5 s for a 5 s clip.

### 5. Enhance a recording

```bash
~/media-stack/tools/voice/voice enhance in.wav out.wav
```
Expected: `out.wav  (highpass 80Hz, comp 3:1, limiter -1dB, loudnorm -> -16.48 LUFS)`.
Output is mono 24 kHz 16-bit. Change target with `--lufs -14`. Reported LUFS
within ±0.5 of target is normal.

### 6. Full pipeline: clone, then check the words

```bash
V=~/media-stack/tools/voice/voice
$V clone --ref REF.wav --ref-text "WORDS IN REF" "NEW TEXT" --out /tmp/c.wav
$V transcribe /tmp/c.wav
$V enhance /tmp/c.wav /tmp/c_clean.wav
```
Pass condition: the `transcribe` line equals NEW TEXT (ignoring punctuation and
case; Whisper writes numbers as digits, e.g. "ten" -> "10").

## Verify

1. `voice status` prints `server: up`.
2. Output file exists and is > 50 000 bytes (`ls -la <out>`). A tiny file means
   the model failed to load: run `~/media-stack/bin/stack logs audio`.
3. `voice transcribe <out>` returns the text you asked for.
4. For clones, optional timbre check (tools venv): MFCC cosine vs the reference
   should be >= 0.985; a different speaker scores ~0.97, the same Kokoro voice ~0.998.

## Measured on this machine (M3 Max 64 GB)

| Step | Cold | Warm | Memory |
|---|---|---|---|
| Kokoro `say` | 20-45 s | 0.1 s | ~0.8 GB server RSS |
| Qwen3-TTS clone via server | 6.4 s | 2.0 s (5 s audio) | +4.5 GB server RSS |
| Qwen3-TTS clone via CLI `mlx_audio.tts.generate` | 10.3 s total, RTF 0.8x | n/a (reloads every run) | 4.7 GB RSS, 9.2 GB MLX peak |
| Chatterbox-turbo clone via server | 109 s (incl. 3 GB download) | 1.9 s | ~3 GB server RSS |
| Whisper turbo transcribe (5 s clip) | 2.9 s | 0.5 s | included above |

Clone similarity (MFCC cosine vs reference / median pitch; reference 199 Hz):
Qwen3-TTS 0.987-0.992 / 186-201 Hz; Chatterbox-turbo 0.989-0.993 / 188-200 Hz;
same Kokoro voice (upper bound) 0.998 / 202 Hz; different speaker (control)
0.971 / 135 Hz. Whisper transcription of every clone matched the requested text
word for word (Chatterbox dropped punctuation; Qwen3 kept it).

## Pitfalls

- **Server path, not upload.** `clone` passes `ref_audio` as an absolute path the
  server opens itself. The CLI resolves it with `os.path.abspath`; the reference
  must be on this Mac's disk.
- **`--ref-text` must be the words actually in the reference.** Wrong text makes
  the clone mumble or stop early. Transcribe the reference first if unsure.
- **Whisper rewrites numbers as digits** ("ten second" -> "10-second"). Compare
  words, not raw strings, when verifying.
- **First request after server start is slow** (20-45 s for Kokoro, ~6-10 s for
  Qwen3-TTS). Do not report that as a hang; run it again before judging speed.
- **Loaded models stay resident.** Kokoro + Qwen3-TTS + Whisper together hold
  ~5 GB. To release: `~/media-stack/bin/stack stop audio` then `start`.
- **`enhance` uses a different venv** (`~/media-stack/tools/.venv`) plus the
  bundled ffmpeg. If it prints `tools venv missing` or `ffmpeg missing`, those
  paths moved; do not install anything with system pip or Homebrew.
- **Long-running commands:** the terminal tool backgrounds anything with
  `timeout > 600`. Keep clone text to a few sentences per call.
- **CLI generator vs server.** `mlx_audio.tts.generate --model ... --ref_audio
  --ref_text --text ... --output_path DIR --file_prefix NAME --audio_format wav`
  also works but reloads 4.3 GB every run; prefer `voice clone` (server) unless
  the server is down and must not be started.
