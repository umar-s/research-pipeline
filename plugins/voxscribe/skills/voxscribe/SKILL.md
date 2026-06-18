---
name: voxscribe
description: Transcribe an audio or video file to text locally. Use whenever the user wants a transcript, subtitles, or "to text" from a media file — triggers include "транскрибируй", "расшифруй (аудио/видео/запись/интервью/лекцию/созвон)", "переведи аудио в текст", "сделай субтитры", "transcribe", "audio to text", "mp3 to text", "video to text", or a path to an .mp3/.wav/.m4a/.mp4/.mkv/... given with intent to get its spoken content as text. Accepts an audio path directly, or a video path (audio is extracted with ffmpeg first). Do NOT use for audio generation, TTS, or music tasks.
---

# voxscribe

Local audio/video → text transcription. Thin wrapper over `openai-whisper` (+`ffmpeg`
to pull the audio track out of video). All mechanics live in the bundled script —
invoke it, then report the output paths and transcript to the user.

## How to run

Resolve the bundled script's absolute path robustly, then run it via `bash` (works even
without the exec bit). `${CLAUDE_PLUGIN_ROOT}` points at this plugin's root when set; the
glob fallback covers `/plugin install` cache layouts when it is not:

    VOX="${CLAUDE_PLUGIN_ROOT:-}/scripts/transcribe.sh"
    [ -f "$VOX" ] || VOX="$(ls "$HOME"/.claude/plugins/*/voxscribe/scripts/transcribe.sh \
        "$HOME"/.claude/plugins/cache/*/voxscribe/*/scripts/transcribe.sh 2>/dev/null | head -1)"
    bash "$VOX" "<path-to-media>" [options]

The script auto-detects audio vs video, picks GPU or CPU by free VRAM, auto-detects the
language, and writes results next to the input file.

## Options (all optional)

| Option | Default | Notes |
|---|---|---|
| `--model` | `small` | tiny / base / small / medium / large. `medium`+ need a big GPU or run slow on CPU. |
| `--language` | `auto` | whisper detects; pass e.g. `--language ru` / `--language en` to force. |
| `--device` | `auto` | `cuda` if it fits free VRAM, else `cpu`. Force with `cpu`/`cuda`. |
| `--out-dir` | input's folder | where results are written. |
| `--formats` | `all` | whisper output formats (txt, srt, vtt, json, tsv). |
| `--keep-audio` | off | keep the extracted wav (video inputs). |

## Output

`<name>.txt` (plain transcript), `<name>.srt` / `<name>.vtt` (timestamped subtitles),
`<name>.json` (segments + timestamps), `<name>.tsv`. The script prints the paths and the
`.txt` content. Exit code `4` + a WARNING means an empty/no-speech transcript (silent or
non-speech input, or the wrong forced language) — not a silent false success.

## Long files / errors

medium/large on CPU is much slower than real time — warn the user before long runs, or use
`--model base`. Missing `whisper`/`ffmpeg` → the script exits with install instructions.
See `references/options.md` for models, VRAM, language codes, and supported environments.
