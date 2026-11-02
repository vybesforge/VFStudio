"""Measure a full-body reference: margins, hand-tip clearance, arm angle.

Answers the questions a vision model is unreliable on — "is this a 45 degree A-pose?"
and "are the hands clipped?" — from pixels instead of a description. Thresholds on
saturation, not luminance: a studio backdrop has a gradient, and a luminance threshold
flags the whole frame as subject.

  python pose_measure.py a.png b.png
      file=... | size=2048x2816 | fig_px=2385 | head_w=319 | shoulder_row=940 |
      margin_left=164 | margin_right=144 | margin_top=312 | margin_bottom=118 |
      margin_side_pct=7.0 | hand_row=1468 | arm_angle_left_deg=59.2 |
      arm_angle_right_deg=57.9 | hand_tip_inside_px=158

  python pose_measure.py --head-crop in.png out.png
      writes an aspect-preserving chin-to-bun crop (never resize it to a square when
      showing it to someone — that is what made a correct head read as "stretched").
"""
import math
import sys

import numpy as np
from PIL import Image

SAT_MIN = 0.10


def mask_of(path):
    a = np.asarray(Image.open(path).convert("RGB")).astype(float)
    mx = a.max(axis=2)
    mn = a.min(axis=2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
    return sat > SAT_MIN


def measure(path):
    m = mask_of(path)
    h, w = m.shape
    rows = np.where(m.sum(axis=1) > 6)[0]
    cols = np.where(m.sum(axis=0) > 6)[0]
    if not len(rows) or not len(cols):
        return {"file": path, "error": "no subject found"}
    top, bot = rows.min(), rows.max()
    left, right = cols.min(), cols.max()
    fig = bot - top

    head_rows = m[top:top + int(fig * 0.12)]
    hc = np.where(head_rows.any(axis=0))[0]
    head_w = (hc.max() - hc.min()) if len(hc) else fig * 0.1

    shoulder_row = None
    for y in range(top + int(fig * 0.05), top + int(fig * 0.35)):
        xs = np.where(m[y])[0]
        if len(xs) and (xs.max() - xs.min()) > 2.2 * head_w:
            shoulder_row = y
            break

    out = {
        "file": path,
        "size": f"{w}x{h}",
        "fig_px": int(fig),
        "head_w": int(head_w),
        "shoulder_row": int(shoulder_row) if shoulder_row else None,
        "margin_left": int(left), "margin_right": int(w - 1 - right),
        "margin_top": int(top), "margin_bottom": int(h - 1 - bot),
        "margin_side_pct": round(100 * min(left, w - 1 - right) / w, 1),
    }
    if shoulder_row:
        widest = None
        for y in range(shoulder_row, top + int(fig * 0.70)):
            xs = np.where(m[y])[0]
            if len(xs) and (widest is None or (xs.max() - xs.min()) > widest[1]):
                widest = (y, xs.max() - xs.min(), xs.min(), xs.max())
        if widest:
            y, _, xmin, xmax = widest
            cx = (hc.min() + hc.max()) / 2 if len(hc) else (left + right) / 2
            dy = max(1, y - shoulder_row)
            out["hand_row"] = int(y)
            out["arm_angle_left_deg"] = round(math.degrees(math.atan2(abs(cx - xmin), dy)), 1)
            out["arm_angle_right_deg"] = round(math.degrees(math.atan2(abs(xmax - cx), dy)), 1)
            out["hand_tip_inside_px"] = int(min(xmin, w - 1 - xmax))
    return out


def head_crop(src, dest, head_frac=0.135, pad=0.62, chin_extra=0.55):
    """chin-to-bun crop from the subject mask, aspect preserved.

    head_frac is the head+neck share of the figure height; chin_extra extends below it
    so the crop reaches past the chin instead of stopping at the eyes.
    """
    im = Image.open(src).convert("RGB")
    m = mask_of(src)
    w, h = im.size
    rows = np.where(m.sum(axis=1) > 6)[0]
    cols = np.where(m.sum(axis=0) > 6)[0]
    top, bot = rows.min(), rows.max()
    fig = bot - top
    head_h = int(fig * head_frac)
    band = m[top:top + head_h]
    bc = np.where(band.any(axis=0))[0]
    cx = (bc.min() + bc.max()) // 2 if len(bc) else (cols.min() + cols.max()) // 2
    half = int(head_h * pad)
    box = (max(0, cx - half), max(0, top - int(head_h * 0.05)),
           min(w, cx + half), min(h, top + head_h + int(head_h * chin_extra)))
    im.crop(box).save(dest)
    print(f"[crop] {dest} box={box}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["--head-crop"]:
        head_crop(args[1], args[2])
    else:
        for p in args:
            d = measure(p)
            print(" | ".join(f"{k}={v}" for k, v in d.items()), flush=True)
