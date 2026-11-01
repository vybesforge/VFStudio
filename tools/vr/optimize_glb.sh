#!/bin/bash
# optimize_glb.sh — shrink a GLB for VR budgets with gltf-transform.
#
# Usage: optimize_glb.sh in.glb out.glb [--target-tris N] [--tex 2048] [--meshopt]
#   --target-tris N   target triangle count (default 100000). Simplify ratio = N / current tris.
#   --tex PX          max texture edge in pixels (default 2048). Textures are never upscaled.
#   --meshopt         ALSO apply EXT_meshopt_compression (+KHR_mesh_quantization).
#                     Default is OFF: Godot 4.7.2's glTF importer rejects both extensions
#                     ("required extension 'EXT_meshopt_compression' is not supported") and the
#                     local WebXR room (~/media-stack/vr/index.html) has no MeshoptDecoder vendored.
#                     Use --meshopt only for a Three.js viewer that registers MeshoptDecoder.
#                     Draco is never used: Godot cannot import it and its decoder is slower/larger.
#
# Pipeline (each step is one gltf-transform command, chained through temp files):
#   dedup -> prune -> weld -> simplify (meshoptimizer) -> resize [-> meshopt]
#
# Prints before/after: file size, triangle count, texture resolutions.
set -euo pipefail

GLTF="$HOME/media-stack/tools/vr/gltf"
IN=""; OUT=""; TARGET=100000; TEX=2048; COMPRESS=0
while [ $# -gt 0 ]; do
  case "$1" in
    --target-tris) TARGET="$2"; shift 2 ;;
    --tex) TEX="$2"; shift 2 ;;
    --meshopt) COMPRESS=1; shift ;;
    --no-compress) COMPRESS=0; shift ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) if [ -z "$IN" ]; then IN="$1"; elif [ -z "$OUT" ]; then OUT="$1"; else echo "unexpected arg $1" >&2; exit 2; fi; shift ;;
  esac
done
[ -n "$IN" ] && [ -n "$OUT" ] || { echo "usage: $0 in.glb out.glb [--target-tris N] [--tex PX] [--meshopt]" >&2; exit 2; }
[ -f "$IN" ] || { echo "input not found: $IN" >&2; exit 1; }
mkdir -p "$(dirname "$OUT")"

# glb_stats <file> [tris]  -> one summary line, or just the triangle count
glb_stats() {
  "$GLTF" inspect "$1" --format csv 2>/dev/null | python3 -c '
import sys, os, csv
f = sys.argv[1]; mode = sys.argv[2] if len(sys.argv) > 2 else ""
tris = 0; tex = []; sec = None; hdr = None
for r in csv.reader(sys.stdin):
    if not r: continue
    if len(r) == 1 and r[0].strip().isupper(): sec = r[0].strip(); hdr = None; continue
    if r[0] == "#": hdr = r; continue
    if hdr and r[0].isdigit():
        if sec == "MESHES": tris += int(r[hdr.index("glPrimitives")].replace(",", ""))
        if sec == "TEXTURES": tex.append(r[hdr.index("resolution")])
t = ",".join(tex) or "none"
if mode == "tris": print(tris)
else: print(f"size={os.path.getsize(f)/1e6:.2f}MB tris={tris:,} textures={t}")
' "$1" "${2:-}"
}

echo "BEFORE: $(glb_stats "$IN")"
CUR_TRIS=$(glb_stats "$IN" tris)
RATIO=$(python3 -c "print(min(1.0, max(0.001, $TARGET / max(1, $CUR_TRIS))))")

TMP="$(mktemp -d "${TMPDIR:-/tmp}/optglb.XXXXXX")"; trap 'rm -rf "$TMP"' EXIT
A="$TMP/a.glb"; B="$TMP/b.glb"
"$GLTF" dedup "$IN" "$A" >/dev/null
"$GLTF" prune "$A" "$B" >/dev/null
"$GLTF" weld "$B" "$A" >/dev/null
echo "simplify: $CUR_TRIS tris -> target $TARGET (ratio $RATIO)"
"$GLTF" simplify "$A" "$B" --ratio "$RATIO" --error 1 >/dev/null
"$GLTF" resize "$B" "$A" --width "$TEX" --height "$TEX" >/dev/null
if [ "$COMPRESS" = 1 ]; then
  "$GLTF" meshopt "$A" "$OUT" --level medium >/dev/null
else
  cp "$A" "$OUT"
fi
echo "AFTER:  $(glb_stats "$OUT")"
echo "wrote $OUT"
