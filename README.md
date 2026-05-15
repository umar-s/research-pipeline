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
git clone https://github.com/<your-user>/research-pipeline ~/Project/research-pipeline
```

In Claude Code, add the directory as a local marketplace:

```
/plugin marketplace add ~/Project/research-pipeline
/plugin install research-pipeline
```

### Option B — direct from GitHub

```
/plugin marketplace add <your-user>/research-pipeline
/plugin install research-pipeline
```

After install, restart Claude Code so the new slash command is registered. Verify:

```
/research-pipeline "test topic"
```

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
/research-pipeline "topic"                              # medium depth, WebSearch
/research-pipeline quick "topic"                        # 3 aspects
/research-pipeline deep "topic"                         # 7 aspects
/research-pipeline deep exa "topic"                     # 7 aspects via Exa
```

Convert the resulting markdown report to PDF (optional):

```bash
pandoc artifacts/{session_id}/FINAL_REPORT.md \
  -o artifacts/{session_id}/FINAL_REPORT.pdf \
  --pdf-engine=xelatex
```

## Layout

```
research-pipeline/
├── .claude-plugin/plugin.json          # plugin metadata
├── commands/research-pipeline.md       # /research-pipeline slash command
├── agents/
│   ├── aspect-researcher.md            # parallel WebSearch worker
│   ├── aspect-researcher-exa.md        # sequential Exa worker
│   └── report-generator.md             # synthesis → final markdown
├── skills/
│   ├── manager-research.md             # 5-phase orchestrator
│   ├── research-planner.md             # topic → aspects + queries
│   ├── synthesis.md                    # cross-aspect aggregation
│   ├── quality-gate.md                 # PASS/WARN/FAIL verdict
│   ├── grounding-protocol.md           # no-hallucination rules
│   ├── silence-protocol.md             # clean parallel execution
│   ├── search-safeguard.md             # retry + jitter for search APIs
│   ├── io-yaml-safe.md                 # safe YAML writes
│   ├── yaml-repair.md                  # auto-fix broken YAML
│   ├── phase-checkpoint.md             # git tag per phase
│   ├── resume-checkpoint.md            # restore from checkpoint
│   └── anti-cringe.md                  # report style guide
├── workflows/research.yaml             # declarative workflow definition
└── templates/skills/                   # skill scaffolding templates
    ├── checkpoint.template.md
    └── repair.template.md
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

Extracted from the satellite-QKD polarization-calibration research project at `/home/serpens/Project/Research`, then refactored to be portable across projects via `${CLAUDE_PLUGIN_ROOT}` path resolution.

## License

MIT.
