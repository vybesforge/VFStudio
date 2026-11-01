---
name: studio-3d-print
description: "Use when asked to design, check, or slice a 3D-printable part on this Mac (parametric CAD -> STL -> G-code/3MF for Bambu Lab or any FDM printer). Fully local: build123d + trimesh + OrcaSlicer CLI."
version: 1.0.0
author: Jimmy
license: MIT
platforms: [macos]
metadata:
  hermes:
    tags: [3d-printing, cad, build123d, stl, orcaslicer, gcode, 3mf, bambu, fdm, makerworld]
    category: studio
---

# Studio: 3D print pipeline (CAD -> STL -> G-code)

Everything runs on this machine, no cloud. Three stages, one tool each:

| Stage | Tool | Command |
|---|---|---|
| 1. Design | build123d (Python CAD) | `~/media-stack/tools/.venv/bin/python <script>.py --out NAME` |
| 2. Check mesh | trimesh + pymeshfix | `~/media-stack/tools/.venv/bin/python ~/media-stack/tools/print/meshcheck.py NAME.stl` |
| 3. Slice | OrcaSlicer 2.4.2 CLI | `~/media-stack/tools/print/slice NAME.stl --preset bambu` |

Owner prints on Bambu Lab (P1S/X1C, 0.4 nozzle, Bambu PLA Basic) and publishes on MakerWorld.
Default to `--preset bambu`. Use `--preset generic` when the part is for "any printer".

## When to use

- "Design/model a bracket/clip/box/mount and make it printable"
- "Is this STL printable? / fix this STL"
- "Slice this for my Bambu / how long will it take / how much filament"
- "Export a 3MF / G-code for MakerWorld or the printer"

## Prerequisites (exact paths — all already installed)

- Python venv: `/Users/dcruse/media-stack/tools/.venv/bin/python` (3.12, build123d 0.13, trimesh 5.2, pymeshfix, networkx). NEVER use `python3` / system Python 3.9.
- OrcaSlicer app: `/Applications/OrcaSlicer.app`; CLI binary: `/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer`
- Bundled printer profiles: `/Applications/OrcaSlicer.app/Contents/Resources/profiles/<Vendor>/{machine,process,filament}/*.json`
- Toolkit: `/Users/dcruse/media-stack/tools/print/`
  - `slice` — slicer wrapper (executable)
  - `meshcheck.py` — printability check / repair
  - `cad_examples/box_with_lid.py`, `cad_examples/magsafe_ring_mount.py`, `cad_examples/cable_clip.py` — parametric templates
- Scratch output: `/Users/dcruse/media-stack/scratch/print-test/` (make a subfolder per job).

Check everything in one line:

```bash
/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer --help 2>&1 | head -1 && ~/media-stack/tools/.venv/bin/python -c "import build123d, trimesh, pymeshfix; print('cad ok')"
```
Expected: `Usage: orca-slicer [ OPTIONS ] [ file.3mf/file.stl ... ]` then `cad ok`.

Add a Python package (never pip from system python):
```bash
$(ls -d ~/.hermes/tools/uv-*/uv) pip install --python ~/media-stack/tools/.venv/bin/python <pkg>
```

## Recipes

### R1 — Generate an example part (parametric box + lid)
```bash
mkdir -p ~/media-stack/scratch/print-test/job1 && cd ~/media-stack/scratch/print-test/job1
~/media-stack/tools/.venv/bin/python ~/media-stack/tools/print/cad_examples/box_with_lid.py --length 60 --width 40 --height 25 --wall 1.6 --tolerance 0.25 --out box
```
Expected:
```
box  60.0x40.0x25.0 wall=1.6  -> box_box.stl
lid  plug clearance=0.25  -> box_lid.stl
both on one plate              -> box.stl  volume=23103 mm^3
```
Other templates (run with `--help` for every flag):
```bash
~/media-stack/tools/.venv/bin/python ~/media-stack/tools/print/cad_examples/magsafe_ring_mount.py --ring-id 56.3 --screws 4 --screw-d 3.4 --screw-head-d 6.5 --out ring_mount
~/media-stack/tools/.venv/bin/python ~/media-stack/tools/print/cad_examples/cable_clip.py --cable-d 6 --opening 4 --out cable_clip
```
Expected (ring): `bbox 77.1 x 77.1 x 7.0 mm  volume=8132 mm^3 -> ring_mount.stl`

### R2 — Write a NEW part with build123d (template to copy)
Save as `part.py`, run with the venv python, always pass `--out`.
```python
#!/usr/bin/env python
import argparse
from build123d import Align, Box, Cylinder, Location, export_stl
p = argparse.ArgumentParser(); p.add_argument("--w", type=float, default=30); p.add_argument("--out", default="part")
a = p.parse_args()
# Build from primitives anchored on Z=0 (Align.MIN on Z) so the part sits on the bed.
body = Box(a.w, 20, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))
hole = Cylinder(2.0, 12, align=(Align.CENTER, Align.CENTER, Align.MIN)).moved(Location((0, 0, -1)))
part = body - hole                       # +  = union, -  = cut
export_stl(part, a.out + ".stl")
print("bbox", part.bounding_box().size, "volume", round(part.volume), "->", a.out + ".stl")
```
Rules that keep the STL watertight: solids must OVERLAP (never just touch/tangent), make cutting tools 1–2 mm longer than the material, use `Align.MIN` on Z so the flat face is the bed.

### R3 — Check an STL is printable
```bash
~/media-stack/tools/.venv/bin/python ~/media-stack/tools/print/meshcheck.py box.stl
```
Expected (exit 0):
```
== box.stl
triangles      : 56  (bodies: 2)
bbox (mm)      : 130.00 x 40.00 x 25.00
watertight     : True
winding ok     : True
volume         : 23103.2 mm^3
PRINTABLE      : YES
```
`PRINTABLE : NO` -> exit 1. Add `--json` for machine output.

### R4 — Repair a broken STL
```bash
~/media-stack/tools/.venv/bin/python ~/media-stack/tools/print/meshcheck.py broken.stl --fix
```
Expected: a `before` block with `watertight : False  (broken faces: N)`, then
```
== after --fix  -> broken_fixed.stl
watertight     : True
PRINTABLE      : YES
```
Exit 0 means the `_fixed.stl` is printable; use THAT file for slicing. Exit 1 = repair failed; regenerate from CAD instead (don't keep patching meshes).

### R5 — Slice for Bambu Lab (P1S/X1C, PLA, 0.2 mm)
```bash
~/media-stack/tools/print/slice box.stl --preset bambu
```
Expected (exit 0, ~10 s):
```
preset   : bambu  (Bambu Lab P1S/X1C, 0.4 nozzle, Bambu PLA Basic, 0.20mm Standard, Textured PEI plate)
gcode    : .../sliced/box/box.gcode
layers   : 125   layer_height 0.2 mm   max_z 25.00 mm
time     : 31m 24s  (model only 25m 9s)
filament : 20.75 g   6845.51 mm   16.47 cm3
printer  : Bambu Lab P1S   nozzle 220C   bed 'Textured PEI Plate'
3mf      : .../sliced/box/box.3mf
```
Outputs land in `./sliced/<name>/` (`--out DIR` to choose). `profiles/*.json` there are the flattened profiles used; `orca.log` is the raw CLI output.

### R6 — Slice for any other printer (generic Marlin / Klipper)
```bash
~/media-stack/tools/print/slice box.stl --preset generic           # Marlin flavour, 250x250x250 bed
~/media-stack/tools/print/slice box.stl --preset generic-klipper   # Klipper flavour
```
Expected: same block, `printer  : Generic Marlin Printer`, `time : 1h 4m 45s`. Bed/limits differ from the user's real printer — only the `.gcode` matters here; tell the user to verify bed size (default 250 mm) or override: `--set printable-area=0x0,220x0,220x220,0x220`.

### R7 — Several parts on one plate / tweak settings
```bash
~/media-stack/tools/print/slice box_box.stl box_lid.stl cable_clip.stl --name plate --preset bambu
~/media-stack/tools/print/slice box.stl --preset bambu --set sparse_infill_density=40% --set wall_loops=3
~/media-stack/tools/print/slice box.stl --preset bambu --set curr_bed_type="Cool Plate"
~/media-stack/tools/print/slice box.stl --preset bambu --json      # machine-readable stats
```
Multiple models auto-arrange. `--set key=value` accepts any OrcaSlicer setting key (underscores or hyphens; the gcode `; key = value` block lists every key). Common ones: `layer_height`, `wall_loops`, `sparse_infill_density`, `enable_support=1`, `support_type=tree(auto)`, `brim_type=outer_only`, `curr_bed_type`.

### R8 — Get the file onto the printer (no cloud needed)
- **Bambu Lab**: the `.3mf` produced by `slice` already contains the G-code (sliced project). Rename it `NAME.gcode.3mf`, then either
  1. copy to the printer's microSD card and start it from the printer screen, or
  2. open it in Bambu Studio / OrcaSlicer GUI (File > Open) and press Print (LAN mode works), or
  3. upload over LAN FTPS (printer in LAN-only mode, access code from the printer screen; UNTESTED here):
     `curl -k --ftp-pasv -u bblp:ACCESSCODE -T NAME.gcode.3mf ftps://PRINTER_IP:990/` then start from the printer screen.
- **Klipper / Marlin / OctoPrint**: upload the `.gcode` (Mainsail/Fluidd web UI, or `curl -F "file=@NAME.gcode" http://PRINTER/server/files/upload` for Moonraker).
- **MakerWorld**: upload the STL(s) and optionally the Bambu `.3mf` as a print profile.

## Verify (run after any change to the toolkit)
```bash
cd ~/media-stack/scratch/print-test && PY=~/media-stack/tools/.venv/bin/python
$PY ~/media-stack/tools/print/cad_examples/cable_clip.py --out cable_clip && \
$PY ~/media-stack/tools/print/meshcheck.py cable_clip.stl && \
~/media-stack/tools/print/slice cable_clip.stl --preset bambu --out sliced/verify && \
ls -la sliced/verify/cable_clip.gcode sliced/verify/cable_clip.3mf && echo VERIFY_OK
```
Expected: `PRINTABLE : YES`, a stats block with `layers : 46`, `filament : 0.71 g`, both files listed, `VERIFY_OK`.

## Designing for FDM — checklist (apply before exporting)
- Walls >= 1.2 mm (3 x 0.4 nozzle = 1.2; use 1.6 for anything structural). Thin features < 0.8 mm won't print.
- Overhangs <= 45° from vertical print unsupported; beyond that add supports (`--set enable_support=1`) or redesign (chamfer the underside instead of a flat overhang; bridge short gaps only).
- Fit tolerances: 0.2 mm per side for snug press fits, 0.3 mm for sliding fits, 0.4–0.5 mm for loose/clearance (holes shrink ~0.2 mm in diameter; a MagSafe puck is 55.9 mm → bore 56.3 mm).
- Screw holes: M3 shank 3.4 mm, head 6.5 mm; M4 shank 4.5 mm, head 8.5 mm. Countersink from the TOP face only (an upside-down countersink is an overhang).
- Orientation: largest flat face down on Z=0, no overhangs facing down, load along the layer plane not across it (layer lines are the weak direction). Print lids/plugs flat side down.
- Keep the part inside the bed: Bambu P1S/X1C = 256 x 256 x 256 mm; generic preset = 250 mm cube.
- Solids in CAD must overlap, never just touch — tangent contacts produce non-watertight STLs (seen with the cable clip ring sitting on its base).
- Horizontal holes print as slightly flattened ovals; make them 0.2 mm bigger or teardrop-shaped.
- Minimum feature height: 0.2 mm (one layer). Text/logos: emboss >= 0.6 mm, line width >= 0.8 mm.

## Pitfalls (actually hit while building this)
- OrcaSlicer CLI does NOT resolve `"inherits"` in the bundled profile JSONs: loading them raw silently drops parent values (filament density came out 0, no gram estimate). `slice` flattens the chain to `sliced/<name>/profiles/*.json`. If you hand-roll a CLI call, point `--load-settings`/`--load-filaments` at those flattened files, not at files inside the .app.
- `--outputdir` must be an ABSOLUTE path and `--export-3mf` a BARE filename (Orca prefixes outputdir itself). Relative outputdir or a path in `--export-3mf` gives `Project export to ... failed` / exit 243 even though plate_1.gcode was written.
- `--load-settings` order is `machine.json;process.json` in ONE semicolon-joined argument; filament goes in `--load-filaments`.
- OrcaSlicer writes `plate_1.gcode`; the wrapper renames it to `<name>.gcode`. Bambu-flavoured gcode has `; total estimated time:` in the header; Marlin-flavoured gcode has `; estimated printing time (normal mode) =` near the end — the parser handles both.
- The Bambu profile defaults to `Cool Plate` (bed 35 °C). The stock P1S/X1C plate is Textured PEI, so the `bambu` preset forces `curr_bed_type=Textured PEI Plate` (bed 55 °C). Override with `--set curr_bed_type="Cool Plate"` if the user says so.
- `trimesh.repair.fill_holes` needs `networkx` (installed) and only closes tiny holes; real repair comes from `pymeshfix` (installed). pymeshfix API: `MeshFix(v, f).repair(joincomp=True, remove_smallest_components=False)` then `.points` / `.faces` (no `.v/.f`, no `verbose=`).
- A build123d cylinder tangent to a plane (ring resting on a plate) yields one edge shared by 4 faces -> `watertight: False` that `--fix` cannot cure. Sink one solid 0.4 mm into the other.
- build123d `Align.MIN` on Z puts the part's bottom at Z=0; without it parts are centred on the origin and half of them is below the bed (Orca drops it to the bed, but your bbox/volume reasoning will be off).
- OrcaSlicer 2.4.2 was installed by copying the .app from the dmg into /Applications + `xattr -dr com.apple.quarantine`. Homebrew is available for updates (`brew install --cask orcaslicer` would replace it). Never attempt `sudo`.
