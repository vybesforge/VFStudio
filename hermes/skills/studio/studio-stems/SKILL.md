---
name: studio-stems
description: "Use when splitting a song into stems or making karaoke."
version: 1.0.0
author: Jimmy
license: Apache-2.0
platforms: [macos, linux]
metadata:
  hermes:
    tags: [studio, stems, demucs, karaoke, vocals, source-separation, mps, local-inference]
    category: studio
---

# Studio Stems

> **Save deliverables under `~/media-stack/output/stems/<song>/`** — that is where the VF Studio panel (http://127.0.0.1:8787) looks; files elsewhere never show up or preview there. Any subfolder inside is fine.

One CLI, `~/media-stack/tools/audio/stems` (also on PATH as `stems`), runs Demucs
(`htdemucs`, Meta's hybrid transformer) on the Apple GPU (`--device mps`) to split
a song into `drums / bass / other / vocals` or into `vocals / no_vocals`
(karaoke). Everything runs on this Mac. Nothing calls a cloud API. Do not add any.

## When to use

- Split a song or a `gen music` output into separate instrument stems (`split`).
- Make an instrumental / karaoke version of a track (`karaoke`).
- Pull an a-cappella vocal out of a mix (`split --two-stems vocals`, take `vocals.wav`).
- Don't use for: speech enhancement (`voice enhance`), transcription (`voice transcribe`),
  making music (`gen music`).

## Prerequisites

| Thing | Exact path / value |
|---|---|
| CLI | `~/media-stack/tools/audio/stems` (symlink `~/.local/bin/stems`) |
| Venv | `~/media-stack/stems/.venv` (python 3.12, torch 2.15, torchaudio 2.11, demucs 4.1.0, soundfile) |
| Device | `mps` is picked automatically; `cpu` only if MPS is missing (prints a warning on stderr) |
| ffmpeg | found as `$FFMPEG` → PATH → `~/.hermes/tools/ffmpeg-*/ffmpeg`; used to decode flac/mp3/m4a to wav before demucs |
| Model cache | `~/.cache/huggingface/hub/models--adefossez--HTDemucs` (htdemucs, 80 MB), `...--HTDemucs-ft` (htdemucs_ft, 4×80 MB). Downloaded on first use. |
| Default output | `~/media-stack/output/stems/<input basename>/<stem>.wav` (44.1 kHz stereo int16) |
| No server | nothing to start; each call loads the model (~2 s) |

Always run this first. It must print `"ok": true` and `"device": "mps"`:

```bash
~/media-stack/tools/audio/stems status
```
Expected (abridged): `{"ok": true, "venv_ok": true, "torch": "2.15.0", "demucs": "4.1.0", "mps_available": true, "device": "mps", "models_cached": {"htdemucs": true, "htdemucs_ft": true, "htdemucs_6s": false, "mdx_extra": false}, ...}`.
`models_cached: false` only means the first run of that model downloads it (needs network).

## Recipes

Use `terminal(command=..., timeout=300)` for every command below. Every command
prints exactly one JSON line at the end:
`{"ok": true, "files": [...], "seconds": 5.2, "model": "htdemucs", "device": "mps", ...}`
or `{"ok": false, "error": "..."}`. Progress/warnings go to stderr.

### 1. Four stems (drums, bass, other, vocals)

```bash
~/media-stack/tools/audio/stems split ~/media-stack/output/music/music_00001.flac
```
Expected: `{"ok": true, "files": ["/Users/dcruse/media-stack/output/stems/music_00001/bass.wav", ".../drums.wav", ".../other.wav", ".../vocals.wav"], "seconds": 7.3, "model": "htdemucs", "device": "mps", ...}`.
Measured on a 30 s track: 7-12 s warm, 26 s the very first time (model download).
Each wav is 5 292 044 bytes for 30 s.

### 2. Karaoke / instrumental (no_vocals only)

```bash
~/media-stack/tools/audio/stems karaoke ~/media-stack/output/music/music_00001.flac --out ~/media-stack/scratch/stems-kar
```
Expected: `{"ok": true, "files": ["/Users/dcruse/media-stack/scratch/stems-kar/no_vocals.wav"], "seconds": 4.2, ...}`.
Measured: 4-6 s for 30 s of audio. Add `--mp3` to get `no_vocals.mp3` (320 kbps, 1.2 MB for 30 s, 11 s).

### 3. Vocals + everything else (a cappella and backing track)

```bash
~/media-stack/tools/audio/stems split ~/media-stack/output/music/music_00001.flac --two-stems vocals --out ~/media-stack/scratch/stems-two
```
Expected: `{"ok": true, "files": [".../stems-two/no_vocals.wav", ".../stems-two/vocals.wav"], "seconds": 5.2, ...}`.
`--two-stems` also accepts `drums`, `bass`, `other`.

### 4. Higher quality (htdemucs_ft, 4 fine-tuned models, ~4× slower)

```bash
~/media-stack/tools/audio/stems split ~/media-stack/output/music/music_00001.flac --model htdemucs_ft --out ~/media-stack/scratch/stems-ft
```
Measured on the 30 s track: 44 s cold (320 MB download), 9 s warm.
Other models accepted but not yet run here: `htdemucs_6s` (adds guitar, piano), `mdx_extra`.

### 5. Options summary

- `--out DIR` any directory; created if missing. Default `~/media-stack/output/stems/<basename>/`.
- `--mp3` write 320 kbps mp3 instead of wav.
- `STEMS_DEVICE=cpu stems split ...` forces CPU (measured 18.8 s vs 7 s on MPS for 30 s).
- Input can be flac, wav, mp3, m4a, ogg, mp4/mov (audio track). Non-wav is decoded with ffmpeg first.

## Verify

Run exactly this block; it must end with `STEMS_OK` (took 6 s here):

```bash
set -e
S=~/media-stack/tools/audio/stems
$S status | grep -q '"ok": true' && echo "status ok"
$S karaoke ~/media-stack/output/music/music_00001.flac --out ~/media-stack/scratch/stems-verify > /tmp/stems_verify.json
grep -q '"ok": true' /tmp/stems_verify.json
test -s ~/media-stack/scratch/stems-verify/no_vocals.wav
~/media-stack/stems/.venv/bin/python -c "import soundfile as sf,numpy as np,os;x,_=sf.read(os.path.expanduser('~/media-stack/scratch/stems-verify/no_vocals.wav'));r=float(np.sqrt((x**2).mean()));print('rms',round(r,4));assert r>0.001,'silent stem'"
cat /tmp/stems_verify.json
echo STEMS_OK
```
Expected: `status ok`, `rms 0.1564`, the JSON line with `"device": "mps"`, then `STEMS_OK`.

Quality numbers measured on `music_00001.flac` (30 s ACE-Step track, htdemucs, mps):
per-stem RMS drums 0.128, bass 0.067, other 0.039, vocals 0.0007 (the track is
instrumental, so a near-silent vocals stem is correct, not a bug); sum of the 4
stems vs the original mix: residual RMS ratio 0.061 (-24 dB). Two-stem: 0.040 (-28 dB).
A ratio above ~0.2 means the stems do not add up to the mix — rerun and check the input.

## Pitfalls

- **Every stem has the same byte size** (5 292 044 for 30 s). That is normal: demucs writes
  full-length wavs. Judge silence by RMS (Verify block), not by file size.
- **A near-silent `vocals.wav` on a `gen music ... --lyrics "[inst]"` track is correct.**
  Check the lyrics you generated with before calling the separation broken.
- **First run of a model needs network** (HF hub download; `status` shows which are cached).
  An offline box fails with a download error inside `"error"`; nothing else is wrong.
- **`PYTORCH_ENABLE_MPS_FALLBACK` made no difference on this torch 2.15 build**: htdemucs ran
  on MPS with and without it (4.7-8.3 s either way, variance is the shared GPU). The CLI sets it
  to 1 by default anyway, and retries on CPU if MPS still errors; look for `"device": "cpu"`
  in the JSON to know a fallback happened.
- **Timings vary 2× when ComfyUI is rendering** (same GPU). Re-measure on an idle box
  before calling it a regression.
- **Do not reuse `~/media-stack/tools/.venv`** for demucs: it needs its own torch; the stems
  venv is separate on purpose (`~/media-stack/stems/.venv`). `uv pip install demucs` alone does
  not pull torchaudio — the installer adds it explicitly.
- **demucs' own file loader is bypassed**: the CLI decodes non-wav inputs with ffmpeg into a temp
  wav inside the output dir (`.demucs_tmp/`, deleted afterwards). If ffmpeg is missing the
  error says `ffmpeg not found (set FFMPEG=...)`.
