# research-pipeline marketplace

A Claude Code **marketplace** that ships two plugins:

- **[research-pipeline](#research-pipeline)** — multi-phase parallel research: decompose a topic into independent aspects, research them in parallel, synthesize, quality-gate, and produce a fully-cited final report.
- **[voxscribe](#voxscribe)** — local audio/video → text transcription via `openai-whisper` (+`ffmpeg` for video), with GPU/CPU auto-selection, language auto-detect, and an output-sanity guard.

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
    │   ├── skills/
    │   │   ├── manager-research.md            # 5-phase orchestrator
    │   │   ├── research-planner.md            # topic → aspects + queries
    │   │   ├── synthesis.md                   # cross-aspect aggregation
    │   │   ├── quality-gate.md                # PASS/WARN/FAIL verdict
    │   │   ├── grounding-protocol.md          # no-hallucination rules
    │   │   ├── silence-protocol.md            # clean parallel execution
    │   │   ├── search-safeguard.md            # retry + jitter for search APIs
    │   │   ├── io-yaml-safe.md                # safe YAML writes
    │   │   ├── yaml-repair.md                 # auto-fix broken YAML
    │   │   ├── phase-checkpoint.md            # git tag per phase
    │   │   ├── resume-checkpoint.md           # restore from checkpoint
    │   │   └── anti-cringe.md                 # report style guide
    │   ├── workflows/research.yaml            # declarative workflow definition
    │   └── templates/skills/                  # skill scaffolding templates
    │       ├── checkpoint.template.md
    │       └── repair.template.md
    └── voxscribe/                             # plugin 2
        ├── .claude-plugin/plugin.json         # plugin metadata
        ├── scripts/transcribe.sh              # ffmpeg + whisper mechanics
        └── skills/voxscribe/
            ├── SKILL.md                       # triggers + how-to-run
            └── references/options.md          # models, VRAM, exit codes, install
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

Local audio/video → text transcription for Claude Code. A thin, robust wrapper over [`openai-whisper`](https://github.com/openai/whisper) (plus `ffmpeg` to pull the audio track out of video). Give it an audio path directly, or a video path — it extracts the audio first — and it writes the transcript next to the input file.

## What it does

- Accepts **audio** (`.mp3`/`.wav`/`.m4a`/...) directly, or **video** (`.mp4`/`.mkv`/...) — for video it extracts a 16 kHz mono wav via `ffmpeg` first.
- Cover-art aware: a tagged podcast `.mp3` (album art = an `attached_pic` video stream) is correctly treated as audio, not video.
- **GPU/CPU auto-selection** — reads free VRAM via `nvidia-smi` and picks `cuda` only if the chosen model fits (with headroom), else falls back to `cpu`. Defaults to the `small` model, which fits common 4 GB GPUs (`medium` would OOM them).
- **Language auto-detect** by default; force with `--language ru` / `--language en` only when you are certain (a wrong forced language makes whisper hallucinate).
- **Output-sanity guard** — whisper exits `0` even on silent/no-speech input; voxscribe checks the result and exits `4` with a WARNING instead of a silent false success.
- Emits `.txt` (plain transcript), `.srt` / `.vtt` (timestamped subtitles), `.json` (segments + timestamps), and `.tsv`.

## Install

```
/plugin marketplace add ~/Project/research-pipeline
/plugin install voxscribe
```

Then **fully restart Claude Code**. Requires `openai-whisper` and `ffmpeg`/`ffprobe` on `PATH`:

```bash
pipx install openai-whisper        # or: pip install -U openai-whisper
sudo apt install ffmpeg            # Debian/Ubuntu  (macOS: brew install ffmpeg)
```

## Usage

The plugin's `voxscribe` skill triggers on transcription requests (e.g. "transcribe this", "расшифруй интервью", "mp3 to text", or a media path with intent to get its text). It resolves the bundled script and runs it. You can also invoke the script directly:

```bash
bash plugins/voxscribe/scripts/transcribe.sh interview.mp4
bash plugins/voxscribe/scripts/transcribe.sh lecture.mp3 --model medium --language ru
```

Options: `--model` (tiny/base/small/medium/large), `--language` (auto/ru/en/...), `--device` (auto/cpu/cuda), `--out-dir`, `--formats`, `--keep-audio`. Exit codes: `0` success, `1` usage/input error, `2` missing dependency, `3` video has no audio, `4` empty/no-speech transcript.

See [`plugins/voxscribe/skills/voxscribe/SKILL.md`](plugins/voxscribe/skills/voxscribe/SKILL.md) and [`references/options.md`](plugins/voxscribe/skills/voxscribe/references/options.md) for models, VRAM logic, language codes, and the supported environment.

## License

MIT.
