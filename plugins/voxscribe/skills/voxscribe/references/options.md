# voxscribe — options & exit codes reference

Engine-level detail for the bundled scripts. Read this only when you need to debug a
specific flag interaction or exit code.

## Models

faster-whisper exposes the OpenAI Whisper model family plus the Distil-Whisper variants
through `ctranslate2`. The model name is passed verbatim to `WhisperModel(model_size_or_path=...)`.

| Model | CPU int8 RAM | Russian quality | When to pick |
|---|---|---|---|
| `tiny` | ~0.5 GB | Weak. Names/morphology break. | Throwaway draft, keyword skim. |
| `base` | ~1 GB | Better but still shaky on Russian. | Quick first pass to confirm the file is what you expect. |
| `small` | ~1.5 GB | Solid for English; passable for Russian. | Mixed-language calls; tight RAM. |
| `medium` | ~3 GB | Notably better Russian, especially proper names. | Day-to-day if `large-v3` is too slow. |
| `large-v3` | ~5 GB | **Default.** Best Russian quality currently available in CTranslate2. | Tafsir lectures, interviews, anything keeping. |

Tip: `--model distil-large-v3` (Distil-Whisper) is ~2× faster than `large-v3` with a small
accuracy drop on Russian. Try when wall-time matters more than the last 5% of accuracy.

## Compute types

Passed as `--compute` to `transcribe_one.py` and forwarded as `compute_type` to
`WhisperModel(...)`:

| `--compute` | Where it makes sense |
|---|---|
| `int8` | **Default** for CPU. Fast, low memory, accurate enough for `large-v3`. |
| `int8_float16` | CUDA with limited VRAM. Whisper internals in fp16, K/V cache in int8. |
| `float16` | CUDA with plenty of VRAM. Slightly higher quality than int8 on long files. |
| `float32` | CPU when you suspect int8 quantization artifacts. Slow. |

## Device selection (`--device`)

`cpu` (default), `cuda`, or `auto`. `auto` doesn't currently do VRAM-aware fallback —
faster-whisper itself will OOM rather than gracefully degrade — so pin to `cpu` or `cuda`
explicitly when running on shared hardware.

For CUDA, voxscribe preloads `nvidia-cublas-cu12` and `nvidia-cudnn-cu12` from the active
Python's site-packages so ctranslate2 finds them without a system-wide CUDA install. The
preload is a no-op when those wheels are absent (the common CPU case).

## Language (`--language`)

Default: `ru`. Pass `auto` to let faster-whisper detect from the first 30 seconds. Risk
(carried over from openai-whisper): forcing the wrong language doesn't error — it
hallucinates a plausible-looking transcript in the forced language. If a transcript looks
like coherent gibberish, suspect a wrong `--language` first.

ISO-639-1 codes: `ru`, `en`, `de`, `fr`, `es`, `it`, `uk`, `kk`, …

## VAD filtering

On by default. Uses Silero VAD bundled with faster-whisper to drop non-speech segments
before decoding — both faster and more accurate on long files with silences/music
intros. Disable with `--no-vad` if VAD is mis-classifying quiet speech as silence
(rare).

## Beam size

Default 5. The faster-whisper sweet spot for Russian. Larger values (10, 20) marginally
improve accuracy at significant CPU cost; not worth it for routine work.

## Output-sanity guard (exit 4)

After transcription, voxscribe checks:

1. `<stem>.txt` exists and is non-empty;
2. at least one segment was emitted to `<stem>.segments.jsonl`.

If both fail, voxscribe prints a `WARNING` and exits **4** instead of writing a misleading
empty `.md` downstream. Common causes:

- Audio is silent or below VAD threshold;
- Wrong `--language` forced (model decoded nothing it considered valid speech);
- Audio is music/SFX/non-speech (whisper occasionally hallucinates filler — VAD catches
  most).

## Engines (`--engine`)

Two backends; pick by tradeoff.

| `--engine` | Pipeline | Strengths | Weaknesses |
|---|---|---|---|
| `faster-whisper` (default) | transcribe → preprocess / (diarize + dialogify + sbert) | Russian sbert punctuation pass; bundled, no extra install; ~5 dependencies | Loose timestamp↔speaker alignment (250–500 ms) on dialogue mode; we maintain the diarization↔text glue |
| `whisperx` | whisperx (faster-whisper + pyannote + forced alignment) in one call | Tight timestamp↔speaker alignment via wav2vec2; one upstream to track | Extra install (`pipx install whisperx`); separate gating for diarization model; no sbert punctuation pass |

Switching engines does not change the file naming convention — both write `<stem>.txt`,
`<stem>.json`, etc. The `--mode dialogue` path under `--engine whisperx` skips our
diarize.py + dialogify.py and lets whisperx produce the speaker-labeled output directly;
`--speakers` is not (yet) propagated to whisperx output.

## Concurrency semaphore (`VOXSCRIBE_MAX_CONCURRENT`)

Folder fan-out spawns N parallel subagents, each calling `transcribe.sh`. Default
`VOXSCRIBE_MAX_CONCURRENT=2` caps the number of concurrent transcription processes via
`flock` on lock files in `${TMPDIR:-/tmp}/voxscribe-cpu-slots/`. Excess subagents wait,
then proceed in FIFO-ish order. Set to `0` to disable.

`VOXSCRIBE_SLOT_TIMEOUT` (default 86400 sec) bounds the wait — beyond it a subagent
exits 1 with a clear message rather than blocking the queue forever.

## RAM warning

At startup the script checks `MemAvailable` from `/proc/meminfo` (Linux only). If less
than 8 GB (lecture) or 10 GB (dialogue) is free, prints `WARNING — only X GB RAM…`.
Not fatal — meant to set expectations and suggest `--model medium` / `--model small`.

## HF preflight (`--skip-hf-preflight`)

Dialogue mode runs a 2-second HuggingFace auth check before kicking off the (potentially
hour-long) transcription, so a missing `HF_TOKEN` or unaccepted-terms surface immediately.
Pass `--skip-hf-preflight` only when:

- the pyannote model is already downloaded into `~/.cache/huggingface/hub/`, AND
- you're offline / behind a flaky proxy, AND
- you're sure the cached weights match the diarization model version voxscribe expects.

Otherwise the preflight is purely beneficial.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success (or all-already-done in folder mode). |
| `1` | Usage / input error (missing argument, unknown option, input not found, unknown `--mode`). |
| `2` | Missing dependency (`ffmpeg`, `ffprobe`, `faster-whisper`, `pyannote.audio`, `transformers`, or `HF_TOKEN`). |
| `3` | Input is a video with **no audio stream** to transcribe. |
| `4` | Ran, but produced an empty / no-speech transcript (the output-sanity guard tripped). |
| anything else | Forwarded exit code from whisper / pyannote / ffmpeg. |

## Cover-art (mp3/m4a with embedded thumbnail)

ffprobe reports cover art as a video stream with `attached_pic=1`. voxscribe filters
these out so a tagged podcast `.mp3` doesn't get wrongly routed through the video branch.
A mp3 with no audio stream at all (unusual) would still trip exit 3 via the audio-stream
check inside the video branch — but that case can't happen for a real audio file.
