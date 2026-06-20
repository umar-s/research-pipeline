# research-pipeline marketplace

A Claude Code **marketplace** that ships two plugins:

- **[research-pipeline](#research-pipeline)** — multi-phase parallel research: decompose a topic into independent aspects, research them in parallel, synthesize, quality-gate, and produce a fully-cited final report.
- **[voxscribe](#voxscribe)** — local audio/video → readable Russian text via `faster-whisper` on CPU. Three modes: lecture (transcribe + paragraph stitching → `.md`), dialogue (transcribe + pyannote diarization + sbert punctuation → speaker turns), folder (fan out parallel subagents over a directory).

Add the marketplace once, then install either plugin:

```
/plugin marketplace add ~/Project/research-pipeline
/plugin install research-pipeline
/plugin install voxscribe
```

After install, **fully restart Claude Code** (exit the session and start a new one — slash commands and skills are only registered at session start).

---

# research-pipeline

A multi-phase parallel research pipeline for Claude Code, packaged as a plugin. Decomposes a topic into independent aspects, researches them in parallel by dedicated worker agents, synthesizes findings across aspects, runs a quality gate, and produces a fully-cited final report.

## What you get

- `/research-pipeline "topic"` — slash command that runs the full 5-phase pipeline in any project.
- **Source tiering** (S/A/B/C/D/X) with recency weights and AI-slop detection.
- **Grounding protocol** — every claim traces to a URL; no hallucinated citations.
- **Quality gate** — PASS/WARN/FAIL verdict before report generation; gaps are surfaced explicitly.
- **Git-based checkpointing** — each phase tagged, supports rollback and resume.
- **Two search backends** — default `WebSearch` (parallel, no setup) or Exa MCP (sequential, semantic, needs API key).

## Pipeline

```
Phase 1        Phase 2           Phase 3       Phase 4        Phase 5
Planning  ───▶ Research ×N ───▶ Synthesis ───▶ Quality ───▶ Report
   │              │                 │             │            │
   ▼              ▼                 ▼             ▼            ▼
plan.yaml    aspects/*.yaml   synthesis.yaml  quality.yaml  FINAL_REPORT.md
```

All outputs land in `./artifacts/{session_id}/` of the current project. Nothing leaks between projects.

## Install

### Option A — local marketplace (one machine)

```bash
git clone https://github.com/umar-s/research-pipeline ~/Project/research-pipeline
```

In Claude Code, add the directory as a local marketplace:

```
/plugin marketplace add ~/Project/research-pipeline
/plugin install research-pipeline
```

### Option B — direct from GitHub

```
/plugin marketplace add umar-s/research-pipeline
/plugin install research-pipeline
```

After install, **fully restart Claude Code** (exit the session and start a new one — `/reload-plugins` is not enough; slash commands are only registered at session start).

## Invocation syntax

Claude Code namespaces plugin slash commands as `/<plugin>:<command>`. Since this plugin is `research-pipeline` and the command file is `research-pipeline.md`, the full invocation is:

```
/research-pipeline:research-pipeline [quick|medium|deep] [exa] "topic"
```

Claude Code's fuzzy matcher also accepts shorter forms like `/research-pipeline:research` or `/research-pipeline:r` — it will resolve to the single command in this plugin and may ask you to confirm before running.

## Prerequisites

### Default mode (WebSearch) — no setup

Works out of the box. Built-in `WebSearch`/`WebFetch` tools must be allowed in your settings.

### Exa mode — optional but recommended for technical research

1. Get an API key at [exa.ai](https://exa.ai).
2. Add to your user-level `~/.claude/settings.json` (NOT to the plugin — keep keys out of git):
   ```json
   {
     "mcpServers": {
       "exa": {
         "command": "npx",
         "args": ["-y", "exa-mcp-server"],
         "env": {
           "EXA_API_KEY": "your-key-here"
         }
       }
     },
     "permissions": {
       "allow": [
         "mcp__exa__web_search_exa",
         "mcp__exa__crawling_exa"
       ]
     }
   }
   ```
3. Restart Claude Code. Verify `mcp__exa__web_search_exa` appears as an available tool.

## Usage

```
/research-pipeline:research-pipeline "topic"                 # medium depth, WebSearch
/research-pipeline:research-pipeline quick "topic"           # 3 aspects
/research-pipeline:research-pipeline deep "topic"            # 7 aspects
/research-pipeline:research-pipeline deep exa "topic"        # 7 aspects via Exa
```

Tab completion in Claude Code helps a lot — type `/research-pipeline:` and pick from the suggestions.

Convert the resulting markdown report to PDF (optional):

```bash
pandoc artifacts/{session_id}/FINAL_REPORT.md \
  -o artifacts/{session_id}/FINAL_REPORT.pdf \
  --pdf-engine=xelatex
```

## Layout

This repo is a Claude Code **marketplace** that ships two plugins. The root holds the marketplace manifest; each plugin lives under `plugins/`.

```
research-pipeline/                             # marketplace root
├── .claude-plugin/marketplace.json            # marketplace catalog (both plugins)
├── README.md
└── plugins/
    ├── research-pipeline/                     # plugin 1
    │   ├── .claude-plugin/plugin.json         # plugin metadata
    │   ├── commands/research-pipeline.md      # /research-pipeline slash command
    │   ├── agents/
    │   │   ├── aspect-researcher.md           # parallel WebSearch worker
    │   │   ├── aspect-researcher-exa.md       # sequential Exa worker
    │   │   └── report-generator.md            # synthesis → final markdown
    │   ├── skills/                            # each skill is a SUBDIR with SKILL.md
    │   │   ├── manager-research/SKILL.md      # 5-phase orchestrator
    │   │   ├── research-planner/SKILL.md      # topic → aspects + queries
    │   │   ├── synthesis/SKILL.md             # cross-aspect aggregation
    │   │   ├── quality-gate/SKILL.md          # PASS/WARN/FAIL verdict
    │   │   ├── grounding-protocol/SKILL.md    # no-hallucination rules
    │   │   ├── silence-protocol/SKILL.md      # clean parallel execution
    │   │   ├── search-safeguard/SKILL.md      # retry + jitter for search APIs
    │   │   ├── io-yaml-safe/SKILL.md          # safe YAML writes
    │   │   ├── yaml-repair/SKILL.md           # auto-fix broken YAML
    │   │   ├── phase-checkpoint/SKILL.md      # git tag per phase
    │   │   ├── resume-checkpoint/SKILL.md     # restore from checkpoint
    │   │   └── anti-cringe/SKILL.md           # report style guide
    │   ├── workflows/research.yaml            # declarative workflow definition
    │   └── templates/skills/                  # skill scaffolding templates
    │       ├── checkpoint.template.md
    │       └── repair.template.md
    └── voxscribe/                             # plugin 2
        ├── .claude-plugin/plugin.json
        ├── Makefile                           # make test (golden fixtures)
        ├── pyproject.toml                     # pytest markers
        ├── scripts/
        │   ├── transcribe.sh                  # bash entry: args, ffmpeg, dispatch, flock
        │   ├── transcribe_one.py              # faster-whisper transcription
        │   ├── preprocess.py                  # paragraph stitching → .md
        │   ├── diarize.py                     # pyannote (dialogue mode)
        │   ├── dialogify.py                   # sbert + speaker-labeled assembly
        │   ├── hf_preflight.py                # fail-fast HF auth check
        │   ├── sbert_punc/                    # bundled apache-2.0 punctuation model
        │   └── tests/                         # golden fixtures + pytest
        └── skills/voxscribe/
            ├── SKILL.md                       # triggers + how-to-run
            └── references/{setup,modes,options}.md
```

## Source quality model

Every source is classified before being used:

| Tier | Weight | Examples |
|------|--------|----------|
| S    | 1.0    | github.com, arxiv.org, official docs, RFCs |
| A    | 0.8    | personal tech blogs, dev.to, HN, lobste.rs |
| B    | 0.6    | Medium (with named author), Stack Overflow |
| C    | 0.4    | news sites, tech aggregators |
| D    | 0.2    | generic content sites |
| X    | 0.0    | SEO farms — skipped |

Recency multiplier: <6mo=1.0, 6-18mo=0.8, 18-36mo=0.6, >36mo=0.4.

Slop detection: sources with >80% AI-generated content are skipped entirely; 60-80% are flagged and down-weighted.

## Notes on naming

The slash command is `/research-pipeline` (not `/research`) to avoid colliding with the simpler `research` skill that ships with the `superpowers` plugin. If you only want this pipeline and not the simple version, you can rename the command file to `research.md` and remove or rename `~/.claude/skills/research/`.

## Origin

Extracted from the satellite-QKD polarization-calibration research project, then refactored to be portable across projects via `${CLAUDE_PLUGIN_ROOT}` path resolution.

---

# voxscribe

Local audio/video → readable Russian text for Claude Code. Backed by [`faster-whisper`](https://github.com/SYSTRAN/faster-whisper) (CPU int8 `large-v3` by default) for transcription, `ffmpeg` for video audio-extraction, and `pyannote.audio` + a bundled apache-2.0 [`sbert_punc_case_ru`](https://huggingface.co/kontur-ai/sbert_punc_case_ru) for the dialogue mode. Optional `--engine whisperx` shells out to upstream WhisperX as a drop-in alternative.

## What it does

- Accepts **audio** (`.mp3`/`.wav`/`.m4a`/`.flac`/`.ogg`/`.opus`), **video** (`.mp4`/`.mkv`/`.mov`/`.webm`/`.avi`, audio-extracted via `ffmpeg`), or a **directory** (folder mode).
- Cover-art aware: a tagged podcast `.mp3` (album art = an `attached_pic` video stream) is correctly treated as audio, not video.
- **Three modes** via `--mode`:
  - `lecture` (default) — `<stem>.txt` + `<stem>.segments.jsonl` + `<stem>.md` (paragraph-stitched, ~140-word paragraphs).
  - `dialogue` — adds pyannote diarization + sbert punctuation → `<stem>.dialogue.md` with `**Имя.** — реплика` and em-dash dialogue. `--speakers "A,B,C"` maps anonymous speakers to names in descending total-speech-time order.
  - `raw` — transcription only (no `.md`).
- **Folder mode** — when input is a directory, voxscribe emits a JSON catalog of media files (with `already_processed` flags) and exits. The skill instructs Claude to fan out one `Agent` per file; a `flock`-based CPU semaphore (`VOXSCRIBE_MAX_CONCURRENT`, default 2) caps real concurrency so the box doesn't thrash.
- **Idempotent** — re-runs skip when outputs exist; `--force` overwrites.
- **Atomic writes** — `.partial → rename` so a crash/kill leaves no corrupt transcripts.
- **Output-sanity guard** — empty / no-speech transcript triggers exit `4` + WARNING (no silent false-greens).
- **Fail-fast dialogue preflight** — checks `HF_TOKEN`, accepted-terms for `pyannote/speaker-diarization-community-1`, and that `pyannote.audio`/`torch` are importable *before* the multi-hour transcription, not after.
- **RAM warning** — if `MemAvailable < 8 GB` (lecture) or `< 10 GB` (dialogue), prints a heads-up at startup with a suggested smaller model.

## Install

```
/plugin marketplace add ~/Project/research-pipeline
/plugin install voxscribe
```

Then **fully restart Claude Code**. Requires `ffmpeg`/`ffprobe` on `PATH` and a Python with `faster-whisper`. voxscribe resolves a Python in this order at every call: `$VOXSCRIBE_PYTHON` → `./.venv/bin/python3` walking up from `$PWD` or the input file → plain `python3`.

```bash
sudo apt install ffmpeg            # Debian/Ubuntu  (macOS: brew install ffmpeg)
python3 -m venv .venv
.venv/bin/pip install faster-whisper                        # lecture mode (≈ 30 MB + 1.5 GB model on first use)

# Additional deps for dialogue mode (≈ 1.5 GB):
.venv/bin/pip install transformers
.venv/bin/pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
.venv/bin/pip install 'pyannote.audio>=4'

# Dialogue mode also needs an HF read-token + accepted terms for the gated model:
#   https://hf.co/settings/tokens  →  create read-token
#   https://hf.co/pyannote/speaker-diarization-community-1  →  Agree and access
export HF_TOKEN=hf_...
```

See [`plugins/voxscribe/skills/voxscribe/references/setup.md`](plugins/voxscribe/skills/voxscribe/references/setup.md) for the full setup walk-through.

## Usage

The plugin's `voxscribe` skill triggers on transcription requests (e.g. "transcribe this", "расшифруй интервью", "mp3 to text", or a media path with intent to get its text). It resolves the bundled script and runs it. You can also invoke the script directly:

```bash
# Single file, lecture mode (default)
bash plugins/voxscribe/scripts/transcribe.sh "Лекция 100626.mp3"

# Meeting / interview with named speakers
HF_TOKEN=hf_... bash plugins/voxscribe/scripts/transcribe.sh meeting.wav \
  --mode dialogue --speakers "Кирилл,Тимур,Умар"

# Folder of recordings — voxscribe lists files, the skill fans out subagents
bash plugins/voxscribe/scripts/transcribe.sh audio/

# Use WhisperX upstream as the engine (must be installed separately)
bash plugins/voxscribe/scripts/transcribe.sh meeting.wav --mode dialogue --engine whisperx
```

Common options: `--mode {lecture|dialogue|raw}`, `--engine {faster-whisper|whisperx}`, `--model` (default `large-v3`), `--language` (default `ru`), `--device` (default `cpu`), `--compute` (default `int8`), `--speakers "A,B,C"`, `--out-dir`, `--no-vad`, `--keep-audio`, `--skip-hf-preflight`, `--force`. Exit codes: `0` success, `1` usage/input error, `2` missing dependency / HF auth, `3` video has no audio, `4` empty/no-speech transcript.

Expected runtime on a 6-core x86-64 with 16+ GB RAM: a 60-minute file is **~60–90 minutes** in lecture mode (RTF ≈ 1.0–1.5 for `large-v3` int8 on CPU), plus an additional **~2–4 hours** for the dialogue-mode pyannote diarization step. Drop to `--model medium` / `--model small` when the wall-time matters more than the last few % of accuracy.

See [`plugins/voxscribe/skills/voxscribe/SKILL.md`](plugins/voxscribe/skills/voxscribe/SKILL.md), [`references/modes.md`](plugins/voxscribe/skills/voxscribe/references/modes.md), [`references/setup.md`](plugins/voxscribe/skills/voxscribe/references/setup.md), and [`references/options.md`](plugins/voxscribe/skills/voxscribe/references/options.md).

## License

MIT.
