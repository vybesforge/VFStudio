#!/usr/bin/env python
"""Parametric box + friction-fit lid (build123d) -> STL.

Exports TWO STLs next to --out: <out>_box.stl and <out>_lid.stl
(and a combined <out>.stl with both parts laid flat side by side for one plate).

Example:
  python box_with_lid.py --length 60 --width 40 --height 25 --wall 1.6 --tolerance 0.25 --out /tmp/box
"""
import argparse
import sys
from pathlib import Path

from build123d import (Align, Box, Location, Mode, Part, export_stl)


def parse():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--length", type=float, default=60.0, help="outer X (mm)")
    p.add_argument("--width", type=float, default=40.0, help="outer Y (mm)")
    p.add_argument("--height", type=float, default=25.0, help="outer Z of box body (mm)")
    p.add_argument("--wall", type=float, default=1.6, help="wall thickness (mm), >= 1.2 for FDM")
    p.add_argument("--floor", type=float, default=1.6, help="floor/lid-top thickness (mm)")
    p.add_argument("--lip", type=float, default=4.0, help="height of lid plug that enters the box (mm)")
    p.add_argument("--tolerance", type=float, default=0.25, help="radial clearance between lid plug and box inner wall (mm)")
    p.add_argument("--out", default="box", help="output path prefix (no extension)")
    return p.parse_args()


def main():
    a = parse()
    if a.wall < 1.2:
        print("WARN: wall < 1.2 mm is weak for FDM", file=sys.stderr)
    L, W, H, t = a.length, a.width, a.height, a.wall
    inner_l, inner_w = L - 2 * t, W - 2 * t
    if inner_l <= 2 * a.tolerance or inner_w <= 2 * a.tolerance:
        sys.exit("ERROR: walls too thick for footprint")

    # Box: outer block minus inner cavity (open top). Anchored on Z=0.
    outer = Box(L, W, H, align=(Align.CENTER, Align.CENTER, Align.MIN))
    cavity = Box(inner_l, inner_w, H - a.floor, align=(Align.CENTER, Align.CENTER, Align.MIN))
    cavity = cavity.moved(Location((0, 0, a.floor)))
    box: Part = outer - cavity

    # Lid: flat top plate (same footprint) + plug that fits inside the cavity with clearance.
    plate = Box(L, W, a.floor, align=(Align.CENTER, Align.CENTER, Align.MIN))
    plug = Box(inner_l - 2 * a.tolerance, inner_w - 2 * a.tolerance, a.lip,
               align=(Align.CENTER, Align.CENTER, Align.MIN)).moved(Location((0, 0, a.floor)))
    lid: Part = plate + plug   # printed plate-down, plug pointing up (no overhangs)

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    export_stl(box, str(out) + "_box.stl")
    export_stl(lid, str(out) + "_lid.stl")
    combined = box + lid.moved(Location((L + 10, 0, 0)))
    export_stl(combined, str(out) + ".stl")
    print(f"box  {L}x{W}x{H} wall={t}  -> {out}_box.stl")
    print(f"lid  plug clearance={a.tolerance}  -> {out}_lid.stl")
    print(f"both on one plate              -> {out}.stl  volume={combined.volume:.0f} mm^3")


if __name__ == "__main__":
    main()
