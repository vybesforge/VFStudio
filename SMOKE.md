# Smoke checklist

Run this on a fresh clone after `install.sh`, `install.ps1`, or `python3 tools/forge/install.py`.
Nothing here names a particular computer. Use whatever GPU the probe reports, including none.

1. **Probe.** `bin/forge-recommend` (Windows: `python tools/forge/recommend.py`).
   The report shows OS, RAM, GPUs, free disk, an engine line (`cuda`, `rocm`, `mlx`, or `cpu`), and three tiers.
2. **Preflight.** `bin/fetch-models --dry-run --profile essentials` lists files and does not download.
   `bin/fetch-models --profile auto` stops before any download if a selected model needs a Hugging Face login.
   Fix with `huggingface-cli login` or `HF_TOKEN`. The token is not written into the repo. `VF_SKIP_GATE=1` continues when you know the URL is public.
3. **One still.** `stack start comfy`, then the smoke line the probe printed (or `gen image "a brass compass" --model klein --seed 1` when klein is in the set).
4. **One speak.** `stack start audio`, then `voice say "hello from the forge"`. On CUDA/ROCm this is speaches, not MLX. If the binary is missing, the panel says so instead of pretending it started.
5. **One stems.** `stems split some.wav` (or `stems status`). Device is CUDA, then Metal, then CPU.
6. **Panel.** `stack panel`, open the Image tab. Generate's hover tip says what it does, and the line under it does not name a folder. Models → **Fetch what fits** uses the same rules as `fetch-models --profile auto`.
7. **Uncensored writer (opt-in).** Apple Silicon's default writer is the labeled uncensored Qwen. On CUDA/ROCm set `VF_UNCENSORED=1` and `WRITER_GGUF` to a local file, then `scribe --uncensored prose "test"`. It is not downloaded for you.

Synthetic checks, no GPU required: `python3 tools/forge/test_recommend.py`.
