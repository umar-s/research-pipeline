---
name: voxscribe
description: Transcribe audio or video to readable Russian text via faster-whisper on CPU. Three modes — lecture (transcribe + paragraph stitching → .md), dialogue (transcribe + pyannote diarization + sbert punctuation → speaker turns), folder (fan out parallel subagents over a directory). Use whenever the user wants a transcript or "to text" from a media file or recording — triggers include "транскрибируй", "расшифруй", "переведи аудио в текст", "transcribe", "audio to text", "video to text", a path to .mp3/.m4a/.wav/.mp4/.mkv/..., or a directory of recordings. Do NOT use for audio generation, TTS, or music tasks.
---

# voxscribe

Local audio/video → readable Russian text. Backed by faster-whisper (CPU int8) for
transcription, ffmpeg for video audio-extraction, and pyannote + sbert for the dialogue
mode. All mechanics live in the bundled scripts — invoke them, then report paths and a
short summary to the user.

## How to run

Resolve the bundled `transcribe.sh` robustly and call it via `bash` (works without exec
bit). `${CLAUDE_PLUGIN_ROOT}` points at this plugin's root when set; the glob fallback
covers `/plugin install` cache layouts when it is not:

    VOX="${CLAUDE_PLUGIN_ROOT:-}/scripts/transcribe.sh"
    [ -f "$VOX" ] || VOX="$(ls "$HOME"/.claude/plugins/*/voxscribe/scripts/transcribe.sh \
        "$HOME"/.claude/plugins/cache/*/voxscribe/*/scripts/transcribe.sh 2>/dev/null | head -1)"
    bash "$VOX" <input> [options]

## Three modes

**Lecture (default).** For a single audio/video file. Produces `<stem>.txt` (raw),
`<stem>.segments.jsonl` (per-segment timestamps), and `<stem>.md` (paragraph-stitched,
~140 words per paragraph). Idempotent — re-runs skip if outputs exist.

    bash "$VOX" "audio/Лекция 100626.mp3"

**Dialogue.** For interviews, meetings, multi-speaker recordings. Adds pyannote
diarization + sbert punctuation. Slow: ~2–3 hours on CPU per 60 min of audio.
Requires `HF_TOKEN` env var and accepted terms for `pyannote/speaker-diarization-community-1`
on HuggingFace. Optionally pass `--speakers` to assign names (in descending total-speech-time
order).

    HF_TOKEN=hf_... bash "$VOX" "audio/meeting.wav" \
      --mode dialogue --speakers "Кирилл,Тимур,Умар"

Output: `<stem>.dialogue.md` with `**Имя.** —` labels and em-dash dialogue.

**Folder.** When `<input>` is a directory, the script prints a JSON list of audio/video
files (with `already_processed` flags) and exits — **the script itself never runs files in
parallel**. The skill (i.e. you, Claude) reads that list and fans out one Agent per
unprocessed file, in a single message with multiple tool calls so they run concurrently.

    # Step 1: list
    bash "$VOX" "audio/"
    # → { "root": "...", "files": [{"path":"audio/a.mp3","already_processed":false}, ...] }

    # Step 2: fan out subagents in a SINGLE assistant message
    # (one Agent call per file with already_processed=false, prompts like:
    #  "Transcribe <path> via voxscribe lecture mode; report stem, paragraph count, RTF.")

Parallelism for the local CPU is bounded by faster-whisper's own threading (large-v3 int8
already uses ~3 cores). On a 6-core i5, **2 parallel agents** is a reasonable ceiling;
don't blow up the box with 5+ simultaneous transcribes.

## Common options

    --mode {lecture|dialogue|raw}   default: lecture
    --engine {faster-whisper|whisperx}  default: faster-whisper
    --model M                       model size                 (default: large-v3)
    --device D                      cpu|cuda|auto              (default: cpu)
    --compute C                     ctranslate2 compute_type   (default: int8)
    --language L                    ISO-639-1 or 'auto'        (default: ru)
    --out-dir O                     defaults to input's folder
    --speakers "A,B,C"              dialogue mode only
    --no-vad                        disable VAD filtering
    --keep-audio                    keep the extracted wav (video inputs)
    --skip-hf-preflight             skip the dialogue HF auth check (offline+cached only)
    --force                         overwrite existing outputs at every step

## Concurrency (folder fan-out)

When the skill fans out parallel subagents, **the bash script's own CPU semaphore caps
real concurrency** — set `VOXSCRIBE_MAX_CONCURRENT` (default 2). Subagents past the cap
wait via `flock` until a slot frees; idempotent and survives kill -9. Set to 0 to disable
the semaphore on machines where you want to manage concurrency externally.

## Output sanity guard

faster-whisper can return zero segments on silent/non-speech audio without raising. The
script exits **4** + prints `WARNING` instead of writing a misleading empty `.md`. Treat
exit 4 as "no speech detected — check input or forced language."

## Expected runtime and memory (set expectations with the user)

Tell the user what to expect **before** kicking off a long run — silent waits feel like
"hung". On a 6-core x86-64 with 16+ GB RAM:

| Mode | 30-min file | 60-min file | 90-min file | Peak RAM (large-v3 int8) |
|---|---|---|---|---|
| lecture | ~30–45 min | ~60–90 min | ~90–150 min | ~3 GB |
| dialogue | ~30–45 min + 1–2 h diarize | ~60–90 min + 2–4 h diarize | ~90–150 min + 3–5 h diarize | ~5 GB (whisper + pyannote both loaded) |

The script issues a RAM warning at startup if `MemAvailable < 8 GB` for lecture or
`< 10 GB` for dialogue. On smaller machines, drop to `--model medium` or `--model small`.

## Errors

- Missing `ffmpeg`/`ffprobe` → exit 2 with install instructions.
- Missing `faster-whisper` in the resolved Python → exit 2 with venv-setup instructions.
- Dialogue mode without `HF_TOKEN` → exit 2 (fail-fast preflight, before transcription).

## Python interpreter resolution

voxscribe picks a Python in this order: `$VOXSCRIBE_PYTHON` → `./.venv/bin/python3` in the
nearest ancestor of `$PWD` or `<input>` → plain `python3`. Tafsir convention is a project
`.venv` with `faster-whisper` installed; voxscribe respects that convention without any
extra config.

See `references/setup.md` for environment setup (venv, faster-whisper, pyannote, sbert),
`references/modes.md` for in-depth mode behavior and outputs, and `references/options.md`
for engine-specific flag details and exit codes.
