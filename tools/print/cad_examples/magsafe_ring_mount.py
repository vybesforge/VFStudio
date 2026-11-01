#!/usr/bin/env python
"""MagSafe-style ring mount with countersunk screw holes (build123d) -> STL.

A flat plate with a raised ring whose inner diameter accepts a MagSafe puck
(56 mm) or a MagSafe-ring magnet array, plus N countersunk M3/M4 holes
around the ring for screwing to a wall / dash / desk.

Example:
  python magsafe_ring_mount.py --ring-id 56.3 --ring-wall 2.4 --ring-height 4 --screws 4 --out /tmp/ring
"""
import argparse
import sys
from pathlib import Path

from build123d import (Align, Axis, Box, Circle, CounterSinkHole, Cylinder, Location, Mode, Part,
                       PolarLocations, Plane, export_stl, extrude, Sketch)


def parse():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ring-id", type=float, default=56.3, help="inner diameter of the ring (mm). MagSafe puck = 55.9; add 0.2-0.4 clearance")
    p.add_argument("--ring-wall", type=float, default=2.4, help="radial wall thickness of the ring (mm)")
    p.add_argument("--ring-height", type=float, default=4.0, help="how far the ring stands above the base plate (mm)")
    p.add_argument("--base", type=float, default=3.0, help="base plate thickness (mm) - must exceed screw head depth")
    p.add_argument("--flange", type=float, default=8.0, help="extra base radius beyond ring outer wall, where screws go (mm)")
    p.add_argument("--screws", type=int, default=4, help="number of countersunk screw holes (0 = none)")
    p.add_argument("--screw-d", type=float, default=3.4, help="screw shank hole diameter (mm). M3 = 3.4, M4 = 4.5")
    p.add_argument("--screw-head-d", type=float, default=6.5, help="countersink head diameter (mm). M3 = 6.5, M4 = 8.5")
    p.add_argument("--cable-slot", type=float, default=0.0, help="width of a cable exit slot through the ring (mm, 0 = none)")
    p.add_argument("--out", default="ring_mount", help="output path prefix (no extension)")
    return p.parse_args()


def main():
    a = parse()
    if a.ring_wall < 1.2:
        print("WARN: ring wall < 1.2 mm is weak for FDM", file=sys.stderr)
    r_in = a.ring_id / 2
    r_out = r_in + a.ring_wall
    r_base = r_out + a.flange
    total_h = a.base + a.ring_height
    if a.base <= 1.0:
        sys.exit("ERROR: base must be > 1 mm to hold a countersink")

    # Base disc + ring, both anchored on Z=0, then cut the ring bore all the way through
    base = Cylinder(r_base, a.base, align=(Align.CENTER, Align.CENTER, Align.MIN))
    ring = Cylinder(r_out, total_h, align=(Align.CENTER, Align.CENTER, Align.MIN))
    bore = Cylinder(r_in, total_h, align=(Align.CENTER, Align.CENTER, Align.MIN))
    part: Part = (base + ring) - bore

    # Countersunk holes from the top face, on a bolt circle midway through the flange
    if a.screws > 0:
        bc_r = r_out + a.flange / 2
        for loc in PolarLocations(bc_r, a.screws):
            x, y, _ = loc.position
            hole = CounterSinkHole(radius=a.screw_d / 2, counter_sink_radius=a.screw_head_d / 2,
                                   depth=a.base + 1, counter_sink_angle=90)
            # CounterSinkHole is defined pointing -Z from its origin; place origin at top of base plate
            part = part - hole.moved(Location((x, y, a.base)))

    if a.cable_slot > 0:
        slot = Box(a.cable_slot, r_out + 1, total_h, align=(Align.CENTER, Align.MIN, Align.MIN))
        part = part - slot

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    export_stl(part, str(out) + ".stl")
    bb = part.bounding_box()
    print(f"ring mount id={a.ring_id} od={2*r_out:.1f} base_od={2*r_base:.1f} h={total_h} screws={a.screws}")
    print(f"bbox {bb.size.X:.1f} x {bb.size.Y:.1f} x {bb.size.Z:.1f} mm  volume={part.volume:.0f} mm^3 -> {out}.stl")


if __name__ == "__main__":
    main()
