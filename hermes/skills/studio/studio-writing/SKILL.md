---
name: studio-writing
description: "Use when writing fiction, scripts, dialogue or lore locally."
version: 1.0.0
author: Jimmy
license: Apache-2.0
platforms: [macos, linux]
metadata:
  hermes:
    tags: [studio, writing, fiction, screenplay, dialogue, lore, llm, mlx-lm, uncensored, local-inference]
    category: studio
---

# studio-writing — local, uncensored creative writing

> **Save deliverables under `~/media-stack/output/text/`** — that is where the VF Studio panel (http://127.0.0.1:8787) looks; files elsewhere never show up or preview there. Any subfolder inside is fine.

A 27B uncensored model (`mlx-community/Qwen3.8-27B-Uncensored-OptiQ-4bit`, ~20 GB) runs in
MLX on this Mac behind `mlx_lm.server` (:8081). `scribe` wraps it with craft-oriented
templates. Cloud models refuse or sanitise adult, violent or morally grey fiction; this one
does not, by Dylan's explicit choice. Prose quality is strong (vivid, specific, in-scene);
it is not a planner — give it the plan.

## When to Use
- Any fiction, screenplay, game dialogue tree, lore/world-bible or revision request where the
  content might be refused or softened by a cloud model, or Dylan says "local".
- Long-form work: outline → chapters → revise, all on-device, files in `output/text/`.
- Not for research/facts: it hallucinates like any 27B. Not for code.

## Prerequisites
```bash
scribe status                 # {"up": true, "models": [...Qwen3.8-27B-Uncensored...]}
stack start llm               # if up:false — loads ~16 GB; ready in 1-2 min; `stack stop llm` frees it
```
`scribe` = `~/media-stack/tools/llm/scribe` (on PATH; it is NOT called `write` — macOS owns that name).
Panel: http://127.0.0.1:8787 → Write tab (mode, premise, genre/POV/tense/words; result pane; files in gallery).
Memory: the LLM + Z-Image + mlx-audio fit together; stop the LLM before Flux dev / Qwen-Edit / TRELLIS runs.

## Recipes
Every command prints one JSON line `{"ok": true, "words": 445, "seconds": 71.8, "out": "..."}` (streams text on a TTY).
Always pass `--out` for anything you want to keep; outputs default to stdout.

**Scene / short fiction** (measured: 445 words in 72 s)
```bash
scribe prose "A lighthouse keeper discovers the fog is listening." --genre "literary horror" --pov third --tense past --words 900 --tone "slow-burn, dry" --out ~/media-stack/output/text/fog.md
```

**Novel outline → chapters**
```bash
scribe outline "premise..." --genre noir --chapters 12 --out ~/media-stack/output/text/outline.md
scribe chapter ~/media-stack/output/text/outline.md --n 1 --words 2500 --out ~/media-stack/output/text/ch01.md
scribe chapter ~/media-stack/output/text/outline.md --n 2 --words 2500 --prev ~/media-stack/output/text/ch01.md --out ~/media-stack/output/text/ch02.md
```
Pass `--prev` every time after chapter 1 — it feeds the last ~6k chars for continuity.

**Screenplay (Fountain)**
```bash
scribe screenplay "logline..." --pages 5 --out ~/media-stack/output/text/scene.fountain
```

**Game dialogue tree (JSON)**
```bash
scribe dialogue "The smuggler wants the player's map; the player needs passage." --chars "Mara, Ivo" --branches 3 --out ~/media-stack/output/text/dock.json
```
Validate with `python3 -m json.tool dock.json`; if the model wrapped it in prose, re-run with `--temp 0.6`.

**Lore / world bible**
```bash
scribe lore "a salt-mining city under a frozen sea" --items 10 --out ~/media-stack/output/text/bible.md
```

**Revise / continue a draft**
```bash
scribe revise draft.md --note "tighten pacing, cut adverbs, more sensory detail" --out draft_v2.md
scribe continue draft.md --words 800 --out draft_more.md
```

**Free prompt with the writer system prompt** — `scribe chat "..."`; `--system "..."` overrides it.

## Craft rules the templates already enforce (keep them in your own prompts)
- Start in scene; no title, no preamble, no summary of what will be written.
- Concrete sensory detail, strong verbs, subtext; distinct voices; no moralising or disclaimers.
- Length is in words; token budget is `words × 2.2` (min 1024) — raise `--max-tokens` for very long asks.

## Verify
```bash
scribe status | grep '"up": true' && scribe prose "test" --words 60 --out /tmp/s.md >/dev/null && test $(wc -w < /tmp/s.md) -gt 30 && echo WRITING_OK
```

## Pitfalls (hit while building)
- **Thinking mode ate the whole budget.** Qwen3.x reasons by default; a 350-word prose request came back EMPTY after 83 s. `scribe` sends `chat_template_kwargs.enable_thinking=false`; `--think` re-enables it (then raise `--max-tokens`).
- **`write` is a macOS binary** (`/usr/bin/write`, "not logged in"). The CLI is `scribe`.
- **HF XET downloads silently produced metadata only.** Fetch weights with `HF_HUB_DISABLE_XET=1 hf download <repo>`.
- Throughput ~6 words/s on this GPU for the 27B; a 2,500-word chapter is ~7 min. Queue chapters, don't babysit.
- `mlx_lm.server` lists every model in the HF cache under `/v1/models`; only the one it was started with is loaded.
