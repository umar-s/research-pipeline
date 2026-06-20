# research-pipeline — Changelog

All notable changes to the **research-pipeline** plugin. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioned independently of
`voxscribe`; follows [SemVer](https://semver.org/).

## [1.1.0] — 2026-06-21

Restructure of `skills/` so Claude Code's plugin loader actually discovers the
12 plugin skills. v1.0.0 shipped flat `skills/<name>.md` files, which the loader
silently ignores — the orchestration command worked, but every `Skill(...)` call
inside it failed at runtime with "Unknown skill". This release makes the skills
visible without changing any behavior.

### Changed

- **`skills/<name>.md` → `skills/<name>/SKILL.md`** for all 12 skills:
  `manager-research`, `research-planner`, `synthesis`, `quality-gate`,
  `phase-checkpoint`, `resume-checkpoint`, `silence-protocol`,
  `search-safeguard`, `io-yaml-safe`, `yaml-repair`, `grounding-protocol`,
  `anti-cringe`. File contents and frontmatter are unchanged — only the path
  changed to match Claude Code's directory-based discovery convention.
- All internal `Skill(skill: "<name>")` references inside `manager-research`,
  `io-yaml-safe`, `phase-checkpoint`, and `resume-checkpoint` upgraded to the
  fully-qualified `research-pipeline:<name>` form. Bare names did not resolve
  under the plugin namespace, so the orchestrator could not invoke its
  sub-skills.

### Fixed

- `agents/aspect-researcher.md` and `agents/aspect-researcher-exa.md`
  `skills.contextual` listed `tier-weights`, `recency-weights`, `slop-check`
  — none of which exist as separate skills. They are inlined tables in the
  agent body; broken references could wedge the agent loader on strict
  validation. Now removed with a comment explaining why.

### Compatibility / migration

Re-install or update the plugin and **fully restart Claude Code** (skill discovery
runs only at session start):

```
/plugin marketplace update research-pipeline
/plugin update research-pipeline
# fully exit and restart Claude Code
```

After restart, the 12 plugin skills should be visible as
`research-pipeline:manager-research`, `research-pipeline:synthesis`, etc.

## [1.0.0] — 2026-06-18

Initial release. 5-phase pipeline (planning → parallel research → synthesis → quality
gate → report), source tiering, grounding protocol, slop detection, two search backends
(WebSearch / Exa MCP), git-based checkpointing. See repo `README.md` for the full
description.

[1.1.0]: https://github.com/umar-s/research-pipeline/compare/research-pipeline-v1.0.0...research-pipeline-v1.1.0
[1.0.0]: https://github.com/umar-s/research-pipeline/releases/tag/research-pipeline-v1.0.0
