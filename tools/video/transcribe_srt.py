#!/Users/dcruse/media-stack/tools/.venv/bin/python
"""transcribe_srt.py — audio/video -> .srt via the LOCAL mlx-audio STT server.

    transcribe_srt.py input.(mp4|mov|wav|mp3|m4a) [out.srt] [--model M] [--language en]
                      [--max-chars 42] [--max-dur 6] [--server http://127.0.0.1:8000]

Video inputs are first converted to 16 kHz mono WAV with ffmpeg. The server is
OpenAI-compatible (POST /v1/audio/transcriptions); nothing leaves this machine.
Strategy: ask for response_format=srt; if the server returns something that is not
SRT, fall back to verbose_json segments (then words) and build the SRT here.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import requests

FFMPEG = str(Path.home() / ".hermes/tools/ffmpeg-9.0.1-darwin-arm64/ffmpeg")
DEFAULT_MODEL = "mlx-community/whisper-large-v3-turbo-asr-fp16"
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac"}


def ts(sec):
    sec = max(0.0, float(sec))
    h = int(sec // 3600); m = int(sec % 3600 // 60); s = int(sec % 60); ms = int(round((sec - int(sec)) * 1000))
    if ms == 1000:
        s += 1; ms = 0
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_wav16k(src, dst):
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", src, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", dst]
    print("$ " + " ".join(cmd), file=sys.stderr)
    subprocess.run(cmd, check=True)


def post(server, wav, model, fmt, language=None, timeout=600):
    data = {"model": model, "response_format": fmt}
    if language:
        data["language"] = language
    if fmt == "verbose_json":
        data["timestamp_granularities[]"] = "segment"
    with open(wav, "rb") as fh:
        r = requests.post(f"{server}/v1/audio/transcriptions", files={"file": (os.path.basename(wav), fh, "audio/wav")}, data=data, timeout=timeout)
    r.raise_for_status()
    return r


def looks_like_srt(text):
    return bool(re.search(r"^\d+\s*\n\d\d:\d\d:\d\d,\d{3} --> \d\d:\d\d:\d\d,\d{3}", text.strip(), re.M))


def segments_to_srt(segments, max_chars, max_dur):
    """segments: list of {start, end, text}. Split long ones on word boundaries."""
    out = []
    for seg in segments:
        text = " ".join(str(seg.get("text", "")).split())
        start, end = float(seg["start"]), float(seg["end"])
        if not text:
            continue
        if len(text) <= max_chars and (end - start) <= max_dur:
            out.append((start, end, text))
            continue
        words = text.split()
        n_parts = max(1, -(-len(text) // max_chars), int(-(-(end - start) // max_dur)))
        per = -(-len(words) // n_parts)
        chunks = [" ".join(words[i:i + per]) for i in range(0, len(words), per)]
        total_chars = sum(len(c) for c in chunks) or 1
        t = start
        for c in chunks:
            d = (end - start) * len(c) / total_chars
            out.append((t, t + d, c))
            t += d
    lines = []
    for i, (s, e, t) in enumerate(out, 1):
        lines.append(f"{i}\n{ts(s)} --> {ts(e)}\n{t}\n")
    return "\n".join(lines)


def words_to_segments(words, max_chars, max_dur):
    segs, cur = [], None
    for w in words:
        wt = str(w.get("word", w.get("text", ""))).strip()
        if not wt:
            continue
        if cur and (len(cur["text"]) + 1 + len(wt) > max_chars or float(w["end"]) - cur["start"] > max_dur):
            segs.append(cur); cur = None
        if cur is None:
            cur = {"start": float(w["start"]), "end": float(w["end"]), "text": wt}
        else:
            cur["text"] += " " + wt; cur["end"] = float(w["end"])
    if cur:
        segs.append(cur)
    return segs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input"); ap.add_argument("output", nargs="?")
    ap.add_argument("--model", default=DEFAULT_MODEL); ap.add_argument("--language", default=None)
    ap.add_argument("--server", default="http://127.0.0.1:8000")
    ap.add_argument("--max-chars", type=int, default=42, help="wrap captions longer than this (when building SRT from segments)")
    ap.add_argument("--max-dur", type=float, default=6.0, help="split captions longer than this many seconds")
    ap.add_argument("--force-json", action="store_true", help="skip response_format=srt, always build from verbose_json")
    a = ap.parse_args()

    src = str(Path(a.input).expanduser())
    out = a.output or str(Path(src).with_suffix(".srt"))
    tmpdir = tempfile.mkdtemp(prefix="srt_", dir=os.environ.get("TMPDIR"))
    wav = os.path.join(tmpdir, "audio16k.wav")
    to_wav16k(src, wav)  # also normalises plain audio to 16 kHz mono, which Whisper wants anyway

    srt = None
    if not a.force_json:
        try:
            r = post(a.server, wav, a.model, "srt", a.language)
            body = r.text
            # some servers wrap the SRT in JSON {"text": "..."}
            if body.lstrip().startswith("{"):
                try:
                    body = json.loads(body).get("text", body)
                except ValueError:
                    pass
            if looks_like_srt(body):
                srt = body.strip() + "\n"
                print("server returned SRT directly", file=sys.stderr)
            else:
                print("response_format=srt did not return SRT; falling back to verbose_json", file=sys.stderr)
        except requests.HTTPError as e:
            print(f"srt request failed ({e}); falling back to verbose_json", file=sys.stderr)
    if srt is None:
        r = post(a.server, wav, a.model, "verbose_json", a.language)
        j = r.json()
        segs = j.get("segments") or []
        if segs and all("start" in s and "end" in s for s in segs):
            print(f"built SRT from {len(segs)} segments", file=sys.stderr)
        elif j.get("words"):
            segs = words_to_segments(j["words"], a.max_chars, a.max_dur)
            print(f"built SRT from {len(j['words'])} words -> {len(segs)} captions", file=sys.stderr)
        else:
            # last resort: one caption spanning the whole file
            dur = float(j.get("duration") or 0) or _wav_duration(wav)
            segs = [{"start": 0.0, "end": dur, "text": j.get("text", "")}]
            print("no timestamps from server; single caption for whole file", file=sys.stderr)
        srt = segments_to_srt(segs, a.max_chars, a.max_dur)

    Path(out).write_text(srt, encoding="utf-8")
    n = len(re.findall(r"^\d+\s*$", srt, re.M))
    print(f"wrote {out} ({n} captions)")
    try:
        os.remove(wav); os.rmdir(tmpdir)
    except OSError:
        pass


def _wav_duration(wav):
    import wave
    with wave.open(wav) as w:
        return w.getnframes() / w.getframerate()


if __name__ == "__main__":
    main()
