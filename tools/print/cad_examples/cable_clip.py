#!/usr/bin/env python
"""Cable clip (C-shaped snap clip on a flat screw/adhesive base) -> STL.

Printed lying on its base; the C opening faces up so no supports are needed.

Example:
  python cable_clip.py --cable-d 6 --opening 4 --out /tmp/clip
"""
import argparse
import sys
from pathlib import Path

from build123d import (Align, Box, Cylinder, Location, Part, export_stl)


def parse():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--cable-d", type=float, default=6.0, help="cable diameter (mm); clip bore = cable-d + 0.3 clearance")
    p.add_argument("--wall", type=float, default=1.6, help="wall thickness of the C (mm)")
    p.add_argument("--opening", type=float, default=4.0, help="gap width of the C opening (mm); smaller than cable-d so it snaps")
    p.add_argument("--depth", type=float, default=10.0, help="clip length along the cable (mm)")
    p.add_argument("--base-w", type=float, default=0.0, help="base plate width (mm, 0 = auto = bore + 2*wall + 6)")
    p.add_argument("--base-t", type=float, default=1.6, help="base plate thickness (mm)")
    p.add_argument("--screw-d", type=float, default=0.0, help="optional screw hole through base (mm, 0 = none, adhesive mount)")
    p.add_argument("--out", default="cable_clip", help="output path prefix (no extension)")
    return p.parse_args()


def main():
    a = parse()
    bore_d = a.cable_d + 0.3
    r_in = bore_d / 2
    r_out = r_in + a.wall
    if a.opening >= bore_d:
        print("WARN: opening >= bore, cable will not be retained", file=sys.stderr)
    base_w = a.base_w or (2 * r_out + 6)
    total_h = a.base_t + 2 * r_out

    # Axis of the cable runs along Y; C ring sits on top of the base plate.
    # The ring is sunk 0.4 mm into the base so the two solids OVERLAP (a cylinder
    # merely tangent to a plane gives a non-manifold edge -> non-watertight STL).
    base = Box(base_w, a.depth, a.base_t, align=(Align.CENTER, Align.CENTER, Align.MIN))
    ring_c = a.base_t + r_in + 0.4
    ring = Cylinder(r_out, a.depth, rotation=(90, 0, 0)).moved(Location((0, 0, ring_c)))
    bore = Cylinder(r_in, a.depth + 2, rotation=(90, 0, 0)).moved(Location((0, 0, ring_c)))
    slot = Box(a.opening, a.depth + 2, r_out + 1, align=(Align.CENTER, Align.CENTER, Align.MIN)).moved(
        Location((0, 0, ring_c)))
    part: Part = (base + ring) - bore - slot

    if a.screw_d > 0:
        # two screw holes in the base, either side of the ring
        off = r_out + (base_w / 2 - r_out) / 2
        for sx in (-off, off):
            part = part - Cylinder(a.screw_d / 2, a.base_t + 2, align=(Align.CENTER, Align.CENTER, Align.MIN)).moved(
                Location((sx, 0, -1)))

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    export_stl(part, str(out) + ".stl")
    bb = part.bounding_box()
    print(f"cable clip bore={bore_d:.1f} opening={a.opening} wall={a.wall} depth={a.depth}")
    print(f"bbox {bb.size.X:.1f} x {bb.size.Y:.1f} x {bb.size.Z:.1f} mm  volume={part.volume:.0f} mm^3 -> {out}.stl")


if __name__ == "__main__":
    main()
