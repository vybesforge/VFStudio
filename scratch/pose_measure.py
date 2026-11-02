"""Measure the A-pose angle and framing margins of a full-body studio reference.

Thresholds on saturation because the studio background is neutral grey — luminance
thresholding fails on the backdrop gradient (it flagged the whole frame as subject).

Prints, per image:
  head_top / feet_bottom rows, left/right subject extent
  hand tip row + x, shoulder joint estimates, arm angle off VERTICAL (deg)
  margin around the extreme subject pixels (px), as a fraction of image width/height

  python pose_measure.py img1.png img2.png ...
"""
import sys

import numpy as np
from PIL import Image


def mask_of(path):
    a = np.asarray(Image.open(path).convert("RGB")).astype(float)
    mx = a.max(axis=2)
    mn = a.min(axis=2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
    return sat > 0.10


def measure(path):
    m = mask_of(path)
    h, w = m.shape
    rows = np.where(m.sum(axis=1) > 6)[0]
    cols = np.where(m.sum(axis=0) > 6)[0]
    top, bot = rows.min(), rows.max()
    left, right = cols.min(), cols.max()
    fig = bot - top
    # shoulder line: first row (below the head) where width exceeds 2.2x the head width
    head_rows = m[top:top + int(fig * 0.12)]
    hc = np.where(head_rows.any(axis=0))[0]
    head_w = hc.max() - hc.min() if len(hc) else fig * 0.1
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
        # hand tips: widest row below the shoulder on each side
        widest = None
        for y in range(shoulder_row, top + int(fig * 0.70)):
            xs = np.where(m[y])[0]
            if len(xs) and (widest is None or (xs.max() - xs.min()) > widest[1]):
                widest = (y, xs.max() - xs.min(), xs.min(), xs.max())
        if widest:
            y, _, xmin, xmax = widest
            # shoulder x approx: interpolate from head centre
            cx = (hc.min() + hc.max()) / 2
            dy = max(1, y - shoulder_row)
            dx_l = abs(cx - xmin)
            dx_r = abs(xmax - cx)
            import math
            out["hand_row"] = int(y)
            out["arm_angle_left_deg"] = round(math.degrees(math.atan2(dx_l, dy)), 1)
            out["arm_angle_right_deg"] = round(math.degrees(math.atan2(dx_r, dy)), 1)
            out["hand_tip_inside_px"] = int(min(xmin, w - 1 - xmax))
    return out


if __name__ == "__main__":
    for p in sys.argv[1:]:
        d = measure(p)
        print(" | ".join(f"{k}={v}" for k, v in d.items()), flush=True)
