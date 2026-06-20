# research-pipeline marketplace — Changelog

This repo is a Claude Code **marketplace** that ships two independently-versioned
plugins. The marketplace catalog itself is also versioned. See per-plugin changelogs
for details:

- [`voxscribe`](plugins/voxscribe/CHANGELOG.md)
- [`research-pipeline`](plugins/research-pipeline/CHANGELOG.md)

## Marketplace catalog

### [1.1.0] — 2026-06-21

- Bundles `research-pipeline@1.1.0` (skills-discovery fix).
- Bundles `voxscribe@2.0.0` (faster-whisper rewrite, BREAKING).
- Catalog `metadata.description` updated to mention both plugins.

### [1.0.0] — 2026-06-18

- Initial catalog with `research-pipeline@1.0.0` and `voxscribe@1.0.0`.

## Releases

Each plugin has its own GitHub release with its own tag. Search the
[releases page](https://github.com/umar-s/research-pipeline/releases) by tag prefix:

- `voxscribe-vX.Y.Z` — voxscribe plugin releases
- `research-pipeline-vX.Y.Z` — research-pipeline plugin releases
