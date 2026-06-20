# voxscribe — Changelog

All notable changes to the **voxscribe** plugin. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This plugin is versioned independently of `research-pipeline` and follows [SemVer](https://semver.org/).

## [2.0.0] — 2026-06-19

Full rewrite over `faster-whisper`. Russian-first defaults, three operating modes, and
parallel-subagent fan-out for folders. Premortem-hardened against 5 specific failure
modes that bit v1 in real Tafsir use.

### Added

- **`--mode lecture`** (default) — transcribe + paragraph stitching → `<stem>.md`
  (~140-word paragraphs).
- **`--mode dialogue`** — adds pyannote diarization + sbert punctuation restoration →
  `<stem>.dialogue.md` with `**Имя.** — реплика` and em-dash dialogue.
  `--speakers "A,B,C"` maps anonymous SPEAKER_NN to names in descending total-speech-time
  order.
- **Folder mode** — when input is a directory, voxscribe emits a JSON catalog of media
  files (`already_processed` flag per file) and exits. The skill instructs Claude to fan
  out one `Agent` per file.
- **`--engine whisperx`** — optional drop-in alternative that shells out to upstream
  [WhisperX](https://github.com/m-bain/whisperX); keeps the same output naming.
- **`flock`-based CPU semaphore** (`VOXSCRIBE_MAX_CONCURRENT`, default 2) so the bash
  script never lets parallel subagents thrash the box (H-001).
- **HF preflight** (`hf_preflight.py`) — checks `HF_TOKEN`, accepted-terms for
  `pyannote/speaker-diarization-community-1`, and `pyannote.audio`/`torch` import
  *before* the multi-hour transcription. `--skip-hf-preflight` for offline + cached
  scenarios (H-002).
- **RAM warning** from `/proc/meminfo` at startup; `< 8 GB` (lecture) or `< 10 GB`
  (dialogue) prints a heads-up with a suggested smaller model (H-003).
- **Bundled sbert punctuation** (`scripts/sbert_punc/`) — Apache-2.0 inference code from
  `kontur-ai/sbert_punc_case_ru`, pinned to commit `f778dc6c…` via
  `revision="..."` in `from_pretrained` (H-005).
- **Golden tests** + `Makefile` (`make test` / `make test-slow`) — paragraph-stitching
  fixtures for `preprocess.py`; sbert smoke test on a Russian fixture.
- `.segments.jsonl` output — per-segment timestamps + text, consumed by `dialogify.py`.
- **Atomic writes** (`.partial → rename`) across all Python scripts so a crash/kill never
  leaves a corrupt transcript.
- **Idempotent skip-if-exists** at every step (transcribe, preprocess, diarize,
  dialogify). `--force` overwrites.
- References docs split into `references/setup.md`, `references/modes.md`,
  `references/options.md`.

### Changed

- **BREAKING — transcription engine** switched from `openai-whisper` CLI to
  `faster-whisper` (CTranslate2). Default model bumped `small` → `large-v3`, default
  compute `fp16/auto` → `int8`, default device `auto` → `cpu`, default language `auto`
  → `ru`.
- **BREAKING — outputs** — `<stem>.srt`, `<stem>.vtt`, `<stem>.tsv` are no longer
  produced. The new pipeline emits `<stem>.txt`, `<stem>.segments.jsonl`, and
  `<stem>.md` (or `<stem>.dialogue.md` in dialogue mode). Subtitles can still be derived
  from `<stem>.segments.jsonl` externally if needed.
- **Python interpreter resolution** is now dynamic per call: `$VOXSCRIBE_PYTHON` →
  `./.venv/bin/python3` walking up from `$PWD` or input → plain `python3`. No more
  bundled Python expectations.
- **Help output** trimmed to the usage block only (was leaking source code below the
  comment block).
- **`--mode` flag is required for non-default behavior**; `dialogue` and `raw` were not
  available in v1.

### Removed

- **BREAKING** — `--formats {txt,srt,vtt,json,tsv}` option (v1) — output formats are now
  fixed per mode. Use `--mode raw` for transcription-only.
- **BREAKING** — `--fp16` option (v1) — replaced by `--compute {int8|int8_float16|float16|float32}`.
- **BREAKING** — `nvidia-smi` VRAM auto-detection — v2 defaults to CPU; pass
  `--device cuda` explicitly when you want GPU, with `--compute float16` or
  `int8_float16` for VRAM-efficient runs.
- **BREAKING** — `openai-whisper` as a required dependency.

### Fixed

- **H-001 / CPU thrashing** — folder fan-out used to depend on Claude orchestrating
  concurrency; now the bash script enforces the CPU cap via `flock`, so 5 parallel
  subagents on a 6-core box run 2-at-a-time with the rest waiting transparently.
- **H-002 / late dialogue auth failure** — used to fail after the 60-min transcription
  with a `huggingface_hub` stacktrace if the token or terms weren't right. Now fails
  in <2 sec at startup with a clear "create token / accept terms / set HF_TOKEN" message.
- **H-003 / silent OOM on long files** — short-clip smoke tests under-estimated runtime
  and RAM. Now warns at startup when `MemAvailable` is below the model's needs.
- **H-005 / sbert as a write-only dependency** — the bundled module now has a source
  URL, pinned commit, Apache-2.0 LICENSE file, and a golden test that fires under
  `make test-slow`.
- Stale `cleanup` trap that could clobber non-zero exit codes from `die`-paths — now
  the cleanup function unconditionally `return 0` so `exit 2/3/4` survives the trap.
- Progress indicator in `transcribe_one.py` (was effectively dead code due to a flawed
  integer-modulo check); now emits one line per minute of audio processed.

### Migration from v1

| v1 invocation | v2 equivalent |
|---|---|
| `transcribe.sh lecture.mp3` | `transcribe.sh lecture.mp3` (now produces `.md` instead of `.srt/.vtt/.tsv`) |
| `transcribe.sh lecture.mp3 --model medium --language ru` | `transcribe.sh lecture.mp3 --model medium` (`--language ru` is the default) |
| `transcribe.sh lecture.mp3 --formats txt,srt` | `transcribe.sh lecture.mp3 --mode raw` (no `.srt` — derive externally from `.segments.jsonl`) |
| `transcribe.sh interview.wav` | `HF_TOKEN=hf_... transcribe.sh interview.wav --mode dialogue --speakers "A,B"` |

## [1.0.0] — 2026-06-18

Initial release. `openai-whisper` CLI wrapper with `ffmpeg` audio extraction for video,
GPU/CPU auto-selection by free VRAM, language auto-detect, output-sanity guard.
Premortem run 1 + run 2 in `docs/premortem/voxscribe.md` (9 holes total).

[2.0.0]: https://github.com/umar-s/research-pipeline/compare/voxscribe-v1.0.0...voxscribe-v2.0.0
[1.0.0]: https://github.com/umar-s/research-pipeline/releases/tag/voxscribe-v1.0.0
