---
description: Run multi-phase research pipeline - decompose topic, research aspects in parallel, synthesize, quality gate, then grounded report
argument-hint: [quick|medium|deep] [exa] topic
allowed-tools: Skill, Read, Write, Glob, Task, TaskOutput, Bash
---

# /deep-research

Run the deep research pipeline over `$ARGUMENTS`.

## Argument parsing

Parse `$ARGUMENTS` left-to-right:

1. **Depth keyword** (optional, first token): `quick` -> 3 aspects, `medium` (default) -> 5 aspects, `deep` -> 7 aspects. Strip it if present.
2. **Search mode keyword** (optional, next token): `exa` -> use Exa MCP (sequential, requires `EXA_API_KEY` and Exa MCP server configured). Otherwise default to built-in `WebSearch` (parallel). Strip if present.
3. **Topic** - everything remaining, with surrounding quotes stripped. Must be non-empty.

If topic is empty after parsing, ask the user for one and stop.

## Session setup

1. Generate session ID: `research_$(date +%Y%m%d)_$(openssl rand -hex 3)`.
2. Create directory: `artifacts/{session_id}/aspects/`.
3. Write initial state to `artifacts/{session_id}/state.yaml`:
   ```yaml
   session_id: {session_id}
   topic: {topic}
   depth: {quick|medium|deep}
   search_mode: {websearch|exa}
   workflow: manager-research
   current_phase: planning
   phase_states:
     planning: pending
     research: pending
     synthesis: pending
     quality_gate: pending
     report: pending
   started_at: {ISO-8601 timestamp}
   ```

## Run the pipeline

Invoke the orchestrator skill - it handles all 5 phases, checkpointing, and recovery:

```
Skill(skill: "research-pipeline:manager-research", args: "topic={topic} depth={depth} search_mode={search_mode} session_id={session_id}")
```

The skill resolves agent files via `${CLAUDE_PLUGIN_ROOT}/agents/...` so it works in any working directory. Outputs land in `./artifacts/{session_id}/` relative to the current project.

## Final deliverable

`artifacts/{session_id}/FINAL_REPORT.md` - fully sourced markdown report. To produce a PDF:

```bash
pandoc artifacts/{session_id}/FINAL_REPORT.md -o artifacts/{session_id}/FINAL_REPORT.pdf --pdf-engine=xelatex
```

## Examples

```
/deep-research "AI agents orchestration patterns"
/deep-research quick "REST API design best practices"
/deep-research deep "Trade-offs between microservices and monoliths in 2026"
/deep-research deep exa "Satellite QKD polarization calibration"
```
