# voxscribe — options reference

Detailed reference for the `transcribe.sh` script: model selection, device/VRAM logic,
language handling, long-file tactics, the output-sanity guard, exit codes, installation,
and the supported environment. Loaded lazily — read this only when you need the deeper
detail behind a flag.

## Models

`openai-whisper` ships five base sizes (plus `.en` English-only variants and a `turbo`
model in recent releases). Pick by the trade-off between VRAM, speed, and accuracy.

| Model | Approx VRAM | Relative speed | Quality (incl. Russian) |
|---|---|---|---|
| `tiny` | ~1 GB | ~10× fastest | Weak. Frequent errors on accented or noisy Russian; usable only for rough drafts or keyword spotting. |
| `base` | ~1 GB | ~7× | Better than tiny but still shaky on Russian morphology and names. Good "fast pass" on long files. |
| `small` | ~2 GB | ~4× | **Default.** Solid Russian and English; a good accuracy/speed balance that fits most 4 GB GPUs. |
| `medium` | ~5 GB | ~2× | Noticeably better Russian, especially names/terms and noisy audio — but needs a real GPU. |
| `large` | ~10 GB | 1× (baseline) | Best quality, including hard Russian audio. Heavy: a sizeable GPU, or very slow on CPU. |

Notes:

- `.en` variants (`tiny.en`, `base.en`, `small.en`, `medium.en`) are English-only and a bit
  more accurate for English — do not use them for Russian or mixed-language audio.
- Russian benefits more than English from going up a size; if a `small` transcript is rough
  on a Russian recording, `--model medium` is the usual next step (GPU permitting).
- The relative-speed numbers are rough rules of thumb, not benchmarks; real throughput
  depends heavily on CPU vs GPU and on the recording.

## Device and VRAM logic

`--device auto` (the default) resolves the device for you:

1. If `nvidia-smi` is absent, the device is **CPU**.
2. If `nvidia-smi` is present, the script reads the **free** VRAM of the first GPU
   (numeric-guarded against `[N/A]`, empty, or multi-GPU output) and compares it against the
   model's estimated need **plus a 15% headroom** (`need_mb = base * 115 / 100`). This avoids
   razor-thin flips where a model "just barely" fits and then OOMs mid-run.
3. If free VRAM is enough → **cuda**; otherwise the script prints why and falls back to **CPU**.

On CPU the script also passes `--fp16 False` (half precision is a GPU feature; forcing it on
CPU triggers a noisy warning and no speedup).

You can override detection entirely with `--device cpu` or `--device cuda`.

### Why `small` is the default

`small` (~2 GB) fits comfortably on a common 4 GB consumer GPU with headroom to spare, while
`medium` (~5 GB) **OOMs a 4 GB GPU** outright. On CPU every size runs, but `medium`/`large`
are significantly slower than real time — a multi-hour recording can take many hours. `small`
is the size that "just works" across the widest range of machines without a surprise OOM or a
runaway CPU run, which is exactly what a zero-config default should do.

## Language

`--language auto` (the default) lets whisper detect the spoken language from the first ~30
seconds of audio. This is the safe choice.

**Risk of forcing the language (H-003):** passing `--language` forces whisper to decode as
that language regardless of what is actually spoken. If you force the *wrong* language,
whisper does not error — it **hallucinates / mistranscribes**, often "translating" or emitting
plausible-looking garbage in the forced language. So force a language only when you are
certain of the content (and want to skip a brief detection step or override a misdetection on
very short clips). Codes are ISO-639-1, e.g. `ru`, `en`, `de`, `fr`, `es`, `uk`.

If a transcript comes out as nonsense in an unexpected language, suspect a wrong forced
`--language` first, and retry with `--language auto`.

## Long files

For long recordings (lectures, hour-plus calls, podcasts):

- Do a fast first pass with `--model base` (or `--model tiny` to just skim) before committing
  a slow high-quality run; confirm the audio is what you expect.
- On CPU, prefer `small`/`base`; `medium`/`large` on CPU can run for many hours. Warn the user
  about expected runtime before starting a long high-model run.
- For video, add `--keep-audio` to retain the extracted 16 kHz mono wav so you can re-run
  different models/languages without re-extracting the audio each time.

## Output-sanity guard (exit 4)

whisper exits `0` even when it transcribed **nothing useful** — silent input, music, or pure
tones produce an empty `.txt` or a hallucinated fragment with zero real segments. The script
guards against this (H-002): after the run it checks that `.txt` has non-whitespace content
**and** that the `.json` has at least one segment. If both fail it prints a `WARNING` and
exits `4` instead of falsely reporting success. Treat exit `4` as "no speech detected — check
that the input actually contains speech, or that the forced `--language` is correct."

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success — a non-empty transcript was written. |
| `1` | Usage / input error (missing argument, unknown option, input not found or unreadable). |
| `2` | A required dependency is missing (`whisper`, `ffmpeg`, or `ffprobe` not in PATH). |
| `3` | Input is a video with **no audio stream** to transcribe. |
| `4` | Ran, but produced an empty / no-speech transcript (the output-sanity guard tripped). |

## Installation

The script does a loud preflight check and tells you exactly what to install if something is
missing. To set up:

```bash
# openai-whisper CLI (Python)
pipx install openai-whisper        # or: pip install -U openai-whisper

# ffmpeg + ffprobe (needed for video audio-extraction and stream probing)
sudo apt install ffmpeg            # Debian/Ubuntu
brew install ffmpeg                # macOS (Homebrew)
```

`whisper` will download model weights on first use; the first run of a new model size is
slower while it fetches.

## Supported environment

**Supported environment (v1):** Linux with the `openai-whisper` CLI (and `ffmpeg`/`ffprobe`
on `PATH`). GPU acceleration is optional and auto-detected; CPU-only works.

**Known limitations:**

- macOS is **not** an officially supported target in v1. The script may run under Homebrew
  `ffmpeg` + `openai-whisper`, but it is untested there and the preflight only checks for the
  three required binaries.
- Alternative engines — `whisper.cpp` and `faster-whisper` — are **not** supported in v1. The
  script invokes the `openai-whisper` CLI specifically; a different `whisper` binary on `PATH`
  will fail loudly at the preflight or argument stage rather than silently misbehaving.
- **CLI-flag drift:** the `openai-whisper` CLI has changed flag names and defaults across
  releases (e.g. `--output_format`, `--fp16`, `--task`). The script targets current
  `openai-whisper`. If a flag is rejected after an upgrade or on an unusually old/new build,
  reconcile the script's `args` array against `whisper --help` for that version.
