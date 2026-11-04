#!/usr/bin/env bash
# new_project.sh — copy a studio Godot template into a new project and print the run/export commands.
#
#   ~/media-stack/game/new_project.sh <2d|3d> <ProjectName> <dest_dir>
#   e.g. ~/media-stack/game/new_project.sh 2d MyPlatformer ~/media-stack/scratch/game-test/MyPlatformer
#
# dest_dir must not exist yet. The template's build/ and .godot/ caches are not copied.
set -euo pipefail

KIND="${1:-}"; NAME="${2:-}"; DEST="${3:-}"
GODOT=/Applications/Godot.app/Contents/MacOS/Godot
TEMPLATES="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/templates"

if [[ -z "$KIND" || -z "$NAME" || -z "$DEST" || ! "$KIND" =~ ^(2d|3d)$ ]]; then
  echo "usage: $0 <2d|3d> <ProjectName> <dest_dir>" >&2; exit 2
fi
SRC="$TEMPLATES/godot-$KIND"
[[ -d "$SRC" ]] || { echo "template missing: $SRC" >&2; exit 1; }
DEST="${DEST/#\~/$HOME}"
[[ -e "$DEST" ]] && { echo "dest exists: $DEST" >&2; exit 1; }

mkdir -p "$DEST"
rsync -a --exclude build/ --exclude .godot/ "$SRC/" "$DEST/"

# rename project + bundle id / product name in project.godot and export_presets.cfg
SLUG="$(echo "$NAME" | tr -cd '[:alnum:]' | tr '[:upper:]' '[:lower:]')"
OLD_NAME="$(sed -n 's/^config\/name="\(.*\)"/\1/p' "$DEST/project.godot")"
OLD_SLUG="$(echo "$OLD_NAME" | tr '[:upper:]' '[:lower:]')"
sed -i '' "s/config\/name=\"$OLD_NAME\"/config\/name=\"$NAME\"/" "$DEST/project.godot"
sed -i '' "s/$OLD_NAME/$NAME/g; s/$OLD_SLUG/$SLUG/g" "$DEST/export_presets.cfg"
sed -i '' "s#export_path=\"build/Game.exe\"#export_path=\"build/$NAME.exe\"#; s#export_path=\"build/Game-macos.zip\"#export_path=\"build/$NAME-macos.zip\"#" "$DEST/export_presets.cfg"

# import once so the first run/export is clean
"$GODOT" --headless --path "$DEST" --import >/dev/null 2>&1 || true

cat <<EOF
created $KIND project "$NAME" at $DEST

# run headless (prints *_READY / GLB_LOAD lines, quits after 5 frames):
$GODOT --headless --path "$DEST" --quit-after 5

# run with a window:
$GODOT --path "$DEST"

# open in the editor:
$GODOT --editor --path "$DEST"

# export (presets: "Windows Desktop", "macOS"):
mkdir -p "$DEST/build"
$GODOT --headless --path "$DEST" --export-release "Windows Desktop" "$DEST/build/$NAME.exe"
$GODOT --headless --path "$DEST" --export-release "macOS" "$DEST/build/$NAME-macos.zip"
EOF
