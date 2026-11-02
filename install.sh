#!/usr/bin/env bash
# install.sh — reproduce the media-stack "studio" on another Apple Silicon Mac.
#
#   git clone <repo> ~/media-stack && cd ~/media-stack && ./install.sh [--all-models] [--hermes] [--no-apps]
#
# Idempotent: every step checks before it acts, so re-running after a failure is safe.
# The install location is fixed at ~/media-stack (scripts, skills and the panel assume it).
#
# What it sets up
#   1. Homebrew (if missing — asks for your password once), uv, ffmpeg, node, sox, git-lfs
#   2. ComfyUI (pinned to COMFYUI_COMMIT) + torch/MPS venv            -> :8188
#   3. mlx-audio venv (TTS / STT / voice clone / music)              -> :8000
#      mlx-lm / mlx-vlm venv: uncensored writer LLM -> :8081, vision VLM (+camera) -> :8082
#   4. tools venv (build123d, trimesh, moviepy, pedalboard, librosa…) for the CLIs
#   5. GUI apps: Blender, Godot (+ export templates), OrcaSlicer, Krita, Audacity, Inkscape,
#      OpenSCAD, MeshLab, Tahoma2D (2D animation)       (skip with --no-apps)
#   6. gltf-transform (npm), symlinks for stack/gen/voice/vid/fetch-models/blender into ~/.local/bin
#   7. Models: essentials by default (~25 GB); --all-models fetches the full manifest (~136 GB)
#   8. --hermes: install the image_gen plugin + studio skills into ~/.hermes and point
#      Hermes' image/tts/stt at the local services
#   9. Starts the panel and runs a smoke test
set -euo pipefail

ALL_MODELS=0; HERMES=0; APPS=1
for a in "$@"; do case "$a" in
  --all-models) ALL_MODELS=1 ;; --hermes) HERMES=1 ;; --no-apps) APPS=0 ;;
  -h|--help) sed -n '2,20p' "$0"; exit 0 ;; *) echo "unknown flag $a" >&2; exit 1 ;; esac; done

STACK="$HOME/media-stack"
HERE="$(cd "$(dirname "$0")" && pwd)"
[ "$HERE" = "$STACK" ] || { echo "This repo must live at $STACK (found $HERE). mv it there and re-run." >&2; exit 1; }
[ "$(uname -s)" = "Darwin" ] && [ "$(uname -m)" = "arm64" ] || { echo "Apple Silicon macOS only." >&2; exit 1; }

say()  { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
ok()   { printf '   \033[32m✓\033[0m %s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

mkdir -p "$STACK"/{logs,run,output,scratch,models} "$HOME/.local/bin"

# ─── 1. base tooling ────────────────────────────────────────────────────────────
say "Homebrew + base tools"
if ! have brew && [ ! -x /opt/homebrew/bin/brew ]; then
  echo "Homebrew is missing. Installing (you will be asked for your macOS password)…"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi
eval "$(/opt/homebrew/bin/brew shellenv)"
grep -q 'brew shellenv' "$HOME/.zprofile" 2>/dev/null || echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> "$HOME/.zprofile"
export HOMEBREW_NO_AUTO_UPDATE=1
for f in uv ffmpeg node sox git-lfs imagesnap; do have "$f" || brew install "$f"; done
ok "brew $(brew --version | head -1 | cut -d' ' -f2) · uv $(uv --version | cut -d' ' -f2) · ffmpeg · node $(node --version) · sox"

# ─── 2. ComfyUI ─────────────────────────────────────────────────────────────────
say "ComfyUI (pinned $(cat "$STACK/COMFYUI_COMMIT" | cut -c1-8))"
if [ ! -d "$STACK/ComfyUI/.git" ]; then
  git clone https://github.com/comfyanonymous/ComfyUI.git "$STACK/ComfyUI"
fi
git -C "$STACK/ComfyUI" fetch -q origin && git -C "$STACK/ComfyUI" checkout -q "$(cat "$STACK/COMFYUI_COMMIT")" || \
  echo "   (could not check out pinned commit; staying on $(git -C "$STACK/ComfyUI" rev-parse --short HEAD))"
if [ ! -x "$STACK/ComfyUI/.venv/bin/python" ]; then
  uv venv --python 3.12 "$STACK/ComfyUI/.venv"
  uv pip install --python "$STACK/ComfyUI/.venv/bin/python" torch torchvision torchaudio
  uv pip install --python "$STACK/ComfyUI/.venv/bin/python" -r "$STACK/ComfyUI/requirements.txt"
fi
"$STACK/ComfyUI/.venv/bin/python" -c "import torch; assert torch.backends.mps.is_available(), 'MPS not available'" && ok "torch MPS ok"
mkdir -p "$STACK/ComfyUI/output"

# ─── 3. mlx-audio ───────────────────────────────────────────────────────────────
say "mlx-audio (TTS / STT / clone / music)"
if [ ! -x "$STACK/audio/.venv/bin/python" ]; then
  mkdir -p "$STACK/audio"; uv venv --python 3.12 "$STACK/audio/.venv"
  uv pip install --python "$STACK/audio/.venv/bin/python" "mlx-audio[server]" --prerelease=allow
  uv pip install --python "$STACK/audio/.venv/bin/python" "misaki[en]" websocket-client fastapi uvicorn requests
fi
"$STACK/audio/.venv/bin/python" -c "import mlx_audio, fastapi, websocket" && ok "mlx-audio $("$STACK/audio/.venv/bin/python" -c 'import importlib.metadata as m;print(m.version("mlx-audio"))')"

# ─── 3b. local LLM + VLM (MLX) ───────────────────────────────────────────────────
say "mlx-lm / mlx-vlm (writer LLM :8081, vision VLM :8082)"
if [ ! -x "$STACK/llm/.venv/bin/python" ]; then
  mkdir -p "$STACK/llm"; uv venv --python 3.12 "$STACK/llm/.venv"
fi
uv pip install -q --python "$STACK/llm/.venv/bin/python" mlx-lm mlx-vlm huggingface_hub
ok "mlx-lm $("$STACK/llm/.venv/bin/python" -c 'import importlib.metadata as m;print(m.version("mlx-lm"))') · mlx-vlm $("$STACK/llm/.venv/bin/python" -c 'import importlib.metadata as m;print(m.version("mlx-vlm"))')"

# ─── 4. tools venv ──────────────────────────────────────────────────────────────
say "tools venv (CAD, mesh, video, audio libs)"
if [ ! -x "$STACK/tools/.venv/bin/python" ]; then
  uv venv --python 3.12 "$STACK/tools/.venv"
fi
uv pip install -q --python "$STACK/tools/.venv/bin/python" build123d trimesh pymeshfix networkx numpy-stl pygltflib \
  moviepy pedalboard librosa soundfile pillow imageio-ffmpeg requests websocket-client scipy
ok "build123d, trimesh, moviepy, pedalboard, librosa"

# Rewrite CLI shebangs to this machine's venvs (they are absolute by necessity)
for f in tools/comfy/gen tools/print/slice tools/video/vid tools/video/transcribe_srt.py; do
  sed -i '' "1s|^#!.*|#!$STACK/tools/.venv/bin/python|" "$STACK/$f"; chmod +x "$STACK/$f"
done
sed -i '' "1s|^#!.*|#!$STACK/audio/.venv/bin/python|" "$STACK/tools/voice/voice"; chmod +x "$STACK/tools/voice/voice"
for f in tools/llm/scribe tools/vision/see; do sed -i '' "1s|^#!.*|#!$STACK/llm/.venv/bin/python|" "$STACK/$f"; chmod +x "$STACK/$f"; done
chmod +x "$STACK"/bin/* "$STACK"/tools/vr/* "$STACK"/tools/print/* 2>/dev/null || true

# ─── 5. apps ────────────────────────────────────────────────────────────────────
if [ "$APPS" = 1 ]; then
  say "GUI apps (brew casks)"
  cask() { local name="$1" app="$2"; [ -d "/Applications/$app" ] && { ok "$app"; return; }; brew install --cask "$name" && ok "$app"; }
  cask blender "Blender.app"
  cask godot "Godot.app"
  cask orcaslicer "OrcaSlicer.app"
  cask krita "Krita.app"
  cask audacity "Audacity 4.app" || cask audacity "Audacity.app"
  cask inkscape "Inkscape.app"
  cask openscad@snapshot "OpenSCAD.app"
  cask meshlab "MeshLab2025.07.app" || true
  # OpenToonz ships x86_64-only on macOS (needs Rosetta + admin); Tahoma2D is the arm64 fork, same .tnz workflow.
  cask tahoma2d "Tahoma2D.app" || echo "   (tahoma2d cask unavailable — download the arm64 dmg from github.com/tahoma2d/tahoma2d/releases)"
  # Godot export templates for the installed version (needed for headless exports)
  if [ -x /Applications/Godot.app/Contents/MacOS/Godot ]; then
    GV="$(/Applications/Godot.app/Contents/MacOS/Godot --headless --version 2>/dev/null | sed -E 's/^([0-9]+\.[0-9]+(\.[0-9]+)?)\.(stable).*/\1.\3/')"
    TD="$HOME/Library/Application Support/Godot/export_templates/$GV"
    if [ ! -f "$TD/version.txt" ]; then
      TAG="${GV%.stable}-stable"
      echo "   fetching Godot export templates $TAG (~1.3 GB)…"
      curl -L --fail --progress-bar -o /tmp/godot_tpz.zip "https://github.com/godotengine/godot/releases/download/$TAG/Godot_v${TAG}_export_templates.tpz" \
        && mkdir -p "$TD" && unzip -qo /tmp/godot_tpz.zip -d /tmp/godot_tpz && mv /tmp/godot_tpz/templates/* "$TD/" && rm -rf /tmp/godot_tpz /tmp/godot_tpz.zip \
        && ok "Godot templates $GV" || echo "   (templates download failed — install from the Godot editor: Editor > Manage Export Templates)"
    else ok "Godot templates $GV"; fi
  fi
fi

# ─── 6. node tools + symlinks ───────────────────────────────────────────────────
say "gltf-transform + command symlinks"
have gltf-transform || npm install -g @gltf-transform/cli >/dev/null
for c in stack fetch-models sync-hermes restore-known-good blender; do ln -sf "$STACK/bin/$c" "$HOME/.local/bin/$c"; done
ln -sf "$STACK/tools/comfy/gen" "$HOME/.local/bin/gen"
ln -sf "$STACK/tools/voice/voice" "$HOME/.local/bin/voice"
ln -sf "$STACK/tools/video/vid" "$HOME/.local/bin/vid"
ln -sf "$STACK/tools/llm/scribe" "$HOME/.local/bin/scribe"
ln -sf "$STACK/tools/vision/see" "$HOME/.local/bin/see"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.zprofile" ;; esac
ok "gen voice vid scribe see stack fetch-models blender -> ~/.local/bin"

# ─── 7. models ──────────────────────────────────────────────────────────────────
say "models"
if [ "$ALL_MODELS" = 1 ]; then
  "$STACK/bin/fetch-models"
else
  # Essentials: fast image + upscalers + SFX + 3D (TRELLIS.2). Voice models download on first use.
  "$STACK/bin/fetch-models" z-image-turbo z-image-te z-image-vae realesrgan-x4plus 4x-ultrasharp \
      stable-audio-open-1.0 t5-base trellis2-int8 trellis2-shape-vae trellis2-texture-vae dinov3-L birefnet
  echo "   essentials done. Everything else: fetch-models            (full list: fetch-models --list)"
fi
# Hugging Face models (LLM, VLM, voice). XET transfer is disabled: with it enabled, weights
# silently failed to land on this network (metadata only) — plain HTTP downloads at full speed.
say "Hugging Face models (models/hf-models.txt)"
export HF_HUB_DISABLE_XET=1
grep -vE '^\s*(#|$)' "$STACK/models/hf-models.txt" | awk '{print $1}' | while read -r repo; do
  if [ "$ALL_MODELS" = 0 ] && [[ "$repo" == *27B* ]]; then echo "   skip $repo (27B writer — fetch with --all-models or: hf download $repo)"; continue; fi
  "$STACK/llm/.venv/bin/hf" download "$repo" >/dev/null 2>&1 && ok "$repo" || echo "   ✗ $repo (re-run install.sh to resume)"
done

# ─── 8. Hermes ──────────────────────────────────────────────────────────────────
if [ "$HERMES" = 1 ]; then say "Hermes integration"; "$STACK/bin/sync-hermes" install; fi

# ─── 9. start + smoke test ──────────────────────────────────────────────────────
say "start panel + services"
export PATH="$HOME/.local/bin:$PATH"
"$STACK/bin/stack" start comfy >/dev/null; "$STACK/bin/stack" start audio >/dev/null
for i in $(seq 1 60); do curl -sf -m 1 http://127.0.0.1:8188/system_stats >/dev/null && break; sleep 2; done
"$STACK/bin/stack" status || true
"$STACK/tools/comfy/gen" status | head -5
echo
echo "Studio panel:  http://127.0.0.1:8787      (open it: stack panel)"
echo "Try:           gen image \"a brass compass on an old map\"      voice say \"hello\"      see snap --ask \"what is this\""
echo "Writer LLM:    stack start llm   (27B, fetched with --all-models)   scribe prose \"premise\" --words 600"
echo "Agent entry:   skill 'studio' (hermes/skills/studio/studio/SKILL.md)"