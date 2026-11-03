#!/usr/bin/env bash
# new_project.sh — stamp a Godot or Three.js project and print how to run it.
#
#   game/new_project.sh <2d|3d|web> <ProjectName> <dest_dir>
#
# web is the Three.js template (alias: three). dest must not exist yet.
set -euo pipefail

KIND="${1:-}"; NAME="${2:-}"; DEST="${3:-}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATES="$ROOT/templates"

case "$KIND" in
  three) KIND=web ;;
esac

if [[ -z "$KIND" || -z "$NAME" || -z "$DEST" || ! "$KIND" =~ ^(2d|3d|web)$ ]]; then
  echo "usage: $0 <2d|3d|web> <ProjectName> <dest_dir>" >&2
  exit 2
fi

if [ "$KIND" = "web" ]; then
  SRC="$TEMPLATES/three-web"
else
  SRC="$TEMPLATES/godot-$KIND"
fi
[[ -d "$SRC" ]] || { echo "template missing: $SRC" >&2; exit 1; }
DEST="${DEST/#\~/$HOME}"
[[ -e "$DEST" ]] && { echo "dest exists: $DEST" >&2; exit 1; }

inplace() {
  # BSD sed (macOS) wants -i ''; GNU sed wants -i.
  if sed --version >/dev/null 2>&1; then
    sed -i "$1" "$2"
  else
    sed -i '' "$1" "$2"
  fi
}

mkdir -p "$DEST"
if command -v rsync >/dev/null 2>&1; then
  rsync -a --exclude build/ --exclude .godot/ --exclude node_modules/ --exclude dist/ "$SRC/" "$DEST/"
else
  cp -R "$SRC/." "$DEST/"
  rm -rf "$DEST/build" "$DEST/.godot" "$DEST/node_modules" "$DEST/dist"
fi

SLUG="$(printf '%s' "$NAME" | tr -cd '[:alnum:]' | tr '[:upper:]' '[:lower:]')"

if [ "$KIND" = "web" ]; then
  inplace "s/\"name\": \"vf-three\"/\"name\": \"$SLUG\"/" "$DEST/package.json"
  inplace "s/<title>VF Three<\\/title>/<title>$NAME<\\/title>/" "$DEST/index.html"
  cat <<EOF
created web project "$NAME" at $DEST

# self-test (no install):
node "$DEST/src/sim.test.mjs"

# play:
cd "$DEST" && npm install && npm run dev

# panel Play button (after a production build):
cd "$DEST" && npm run build
EOF
  exit 0
fi

OLD_NAME="$(sed -n 's/^config\/name="\(.*\)"/\1/p' "$DEST/project.godot")"
OLD_SLUG="$(printf '%s' "$OLD_NAME" | tr '[:upper:]' '[:lower:]')"
inplace "s/config\\/name=\\\"$OLD_NAME\\\"/config\\/name=\\\"$NAME\\\"/" "$DEST/project.godot"
inplace "s/$OLD_NAME/$NAME/g; s/$OLD_SLUG/$SLUG/g" "$DEST/export_presets.cfg"
inplace "s#export_path=\\\"build/Game.exe\\\"#export_path=\\\"build/$NAME.exe\\\"#; s#export_path=\\\"build/Game-macos.zip\\\"#export_path=\\\"build/$NAME-macos.zip\\\"#" "$DEST/export_presets.cfg"

G="${GODOT:-}"
if [ -z "$G" ]; then
  if [ -x /Applications/Godot.app/Contents/MacOS/Godot ]; then
    G=/Applications/Godot.app/Contents/MacOS/Godot
  elif command -v godot >/dev/null 2>&1; then
    G="$(command -v godot)"
  elif command -v godot4 >/dev/null 2>&1; then
    G="$(command -v godot4)"
  fi
fi
if [ -n "$G" ]; then
  "$G" --headless --path "$DEST" --import >/dev/null 2>&1 || true
else
  echo "note: godot not on PATH and GODOT is unset — project copied, import skipped" >&2
  G="godot"
fi

cat <<EOF
created $KIND project "$NAME" at $DEST

# run headless (prints *_READY / GLB_LOAD lines, quits after 5 frames):
$G --headless --path "$DEST" --quit-after 5

# run with a window:
$G --path "$DEST"

# open in the editor:
$G --editor --path "$DEST"

# export (presets: "Windows Desktop", "macOS"; Linux preset is not in the template):
mkdir -p "$DEST/build"
$G --headless --path "$DEST" --export-release "Windows Desktop" "$DEST/build/$NAME.exe"
$G --headless --path "$DEST" --export-release "macOS" "$DEST/build/$NAME-macos.zip"
EOF
