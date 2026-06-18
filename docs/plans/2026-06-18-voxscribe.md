# voxscribe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.
> Steps use checkbox (`- [ ]`) syntax.

**Goal:** Плагин `voxscribe` (2-й в marketplace research-pipeline): путь к аудио/видео → текст
(+srt/vtt/json) локально через openai-whisper (+ffmpeg для видео).

**Architecture:** `SKILL.md` (триггеры+инструкция) + bundled `scripts/transcribe.sh` (вся механика:
preflight, ffprobe-детект, ffmpeg-extract, device/VRAM-выбор, language auto, whisper, output-guard).

**Tech Stack:** bash, ffmpeg/ffprobe 6.x, openai-whisper CLI, JSON-манифесты Claude Code plugin.

**Spec:** `docs/specs/2026-06-18-voxscribe-design.md`. **Premortem:** `docs/premortem/voxscribe.md`
(run-1: H-001 device/OOM, H-002 output-guard, H-003 language auto, H-004 marketplace sync, H-005 preflight).

**Branch:** `feat/voxscribe` (уже создана).

---

### Task 1: plugin.json + marketplace entry (H-004)

**Files:** Create `plugins/voxscribe/.claude-plugin/plugin.json`; Modify `.claude-plugin/marketplace.json`

- [ ] **Step 1:** Create `plugins/voxscribe/.claude-plugin/plugin.json`:

```json
{
  "name": "voxscribe",
  "version": "1.0.0",
  "description": "Transcribe audio or video files to text locally with openai-whisper. Accepts an audio path directly, or a video path (extracts the audio track via ffmpeg first). Emits .txt + timestamped .srt/.vtt + .json. Auto-detects GPU VRAM and falls back to CPU, auto-detects language, and guards against silent empty/no-speech output.",
  "author": { "name": "Sergei", "email": "sergei.bitsmedia@gmail.com" },
  "license": "MIT",
  "keywords": ["transcription", "whisper", "speech-to-text", "subtitles", "ffmpeg", "audio", "video"]
}
```

- [ ] **Step 2:** В `.claude-plugin/marketplace.json` добавить ВТОРЫМ элементом `plugins[]` (после существующего research-pipeline; existing запись не трогать):

```json
    {
      "name": "voxscribe",
      "source": "./plugins/voxscribe",
      "description": "Local audio/video → text transcription via openai-whisper. Audio path direct, video path via ffmpeg audio-extract. Emits txt + srt/vtt + json. GPU-VRAM-aware device fallback, language auto-detect, and an output-sanity guard against silent no-speech transcripts.",
      "version": "1.0.0",
      "author": { "name": "Sergei", "email": "sergei.bitsmedia@gmail.com" },
      "repository": "https://github.com/umar-s/research-pipeline",
      "license": "MIT",
      "keywords": ["transcription", "whisper", "speech-to-text", "subtitles", "ffmpeg"],
      "category": "media",
      "tags": ["transcription", "whisper", "audio", "video"]
    }
```

- [ ] **Step 3:** Validate: `python3 -m json.tool .claude-plugin/marketplace.json >/dev/null && python3 -m json.tool plugins/voxscribe/.claude-plugin/plugin.json >/dev/null && echo OK`. `plugins[].name` для voxscribe == `plugin.json.name` == `"voxscribe"`; `source` == `"./plugins/voxscribe"` (реальный каталог). Existing research-pipeline запись осталась.

---

### Task 2: scripts/transcribe.sh (H-001/H-002/H-003/H-005/H-007/H-008)

**Files:** Create `plugins/voxscribe/scripts/transcribe.sh` (chmod +x)
**H-006:** скрипт лежит в КОРНЕ плагина (`plugins/voxscribe/scripts/`), НЕ в `skills/...` —
тогда `${CLAUDE_PLUGIN_ROOT}/scripts/transcribe.sh` резолвится чисто (паттерн GTD planning-with-files).

- [ ] **Step 1:** Создать скрипт ДОСЛОВНО:

```bash
#!/usr/bin/env bash
# voxscribe — transcribe audio/video to text via openai-whisper (+ffmpeg for video).
# Usage: transcribe.sh <input-file> [--model M] [--language L] [--device D]
#                      [--out-dir O] [--formats F] [--keep-audio]
# Defaults: --model small  --language auto  --device auto  --formats all
#           --out-dir = directory of input file
set -euo pipefail

die() { echo "voxscribe: $*" >&2; exit "${2:-1}"; }

MODEL=small; LANGUAGE=auto; DEVICE=auto; OUTDIR=""; FORMATS=all; KEEP_AUDIO=0; INPUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
    --model) MODEL="${2:?}"; shift 2 ;;
    --language) LANGUAGE="${2:?}"; shift 2 ;;
    --device) DEVICE="${2:?}"; shift 2 ;;
    --out-dir) OUTDIR="${2:?}"; shift 2 ;;
    --formats) FORMATS="${2:?}"; shift 2 ;;
    --keep-audio) KEEP_AUDIO=1; shift ;;
    --) shift; break ;;
    -*) die "unknown option: $1" 1 ;;
    *) [ -z "$INPUT" ] && INPUT="$1" || die "unexpected arg: $1" 1; shift ;;
  esac
done
[ -n "$INPUT" ] || die "usage: transcribe.sh <input-file> [options]" 1

# H-005: preflight dependencies — loud, actionable failure (not a silent traceback)
for bin in whisper ffmpeg ffprobe; do
  command -v "$bin" >/dev/null 2>&1 || die \
    "'$bin' not found in PATH. Install: openai-whisper (pipx install openai-whisper), ffmpeg (apt/brew install ffmpeg). v1 supports openai-whisper on Linux." 2
done

[ -f "$INPUT" ] && [ -r "$INPUT" ] || die "input not found/readable: $INPUT" 1
[ -n "$OUTDIR" ] || OUTDIR="$(dirname -- "$INPUT")"
mkdir -p -- "$OUTDIR"

# Output basename is ALWAYS derived from the original input (not the temp wav)
in_base="$(basename -- "$INPUT")"; STEM="${in_base%.*}"

# H-008: a "real" video stream is one whose attached_pic disposition is 0.
# Cover-art / album-art in mp3/m4a is a video stream with attached_pic=1 and MUST be
# treated as audio (otherwise every tagged podcast mp3 wrongly goes through ffmpeg).
real_video="$(ffprobe -v error -select_streams v -show_entries stream_disposition=attached_pic -of csv=p=0 -- "$INPUT" 2>/dev/null | grep -c '^0$' || true)"

TMP_DIR=""; cleanup() { [ -n "$TMP_DIR" ] && [ "$KEEP_AUDIO" -eq 0 ] && rm -rf -- "$TMP_DIR"; }
trap cleanup EXIT

AUDIO_IN="$INPUT"
if [ "${real_video:-0}" -gt 0 ]; then
  has_audio="$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_type -of csv=p=0 -- "$INPUT" 2>/dev/null || true)"
  [ -n "$has_audio" ] || die "video has no audio stream: $INPUT" 3
  TMP_DIR="$(mktemp -d)"
  AUDIO_IN="$TMP_DIR/$STEM.wav"   # named after original stem → whisper outputs $STEM.*
  echo "voxscribe: extracting audio from video ..." >&2
  ffmpeg -nostdin -v error -i "$INPUT" -vn -ac 1 -ar 16000 -c:a pcm_s16le -y -- "$AUDIO_IN"
fi

# H-001: device/VRAM-aware selection (default model 'small'; medium OOMs a 4GB GPU)
model_vram_mb() { case "$1" in
  tiny*|base*) echo 1500 ;; small*) echo 2500 ;; medium*) echo 5000 ;;
  large*|turbo) echo 10000 ;; *) echo 2500 ;; esac; }
DEV="$DEVICE"
if [ "$DEV" = auto ]; then
  DEV=cpu
  if command -v nvidia-smi >/dev/null 2>&1; then
    # H-007: read free VRAM of the FIRST gpu; numeric-guard against [N/A]/empty/multi-line.
    free_mb="$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -dc '0-9' || true)"
    need_mb=$(( $(model_vram_mb "$MODEL") * 115 / 100 ))   # +15% headroom — avoid razor-thin flips
    if [ -z "${free_mb:-}" ]; then
      echo "voxscribe: could not read GPU VRAM (nvidia-smi returned non-numeric) -> CPU" >&2
    elif [ "$free_mb" -ge "$need_mb" ]; then DEV=cuda
    else echo "voxscribe: GPU free ${free_mb}MiB < ${need_mb}MiB needed for '$MODEL' -> CPU" >&2; fi
  fi
fi
echo "voxscribe: device=$DEV" >&2

args=(--model "$MODEL" --device "$DEV" --output_format "$FORMATS" --output_dir "$OUTDIR" --task transcribe --verbose False)
[ "$DEV" = cpu ] && args+=(--fp16 False)
[ "$LANGUAGE" != auto ] && args+=(--language "$LANGUAGE")   # H-003: no --language => whisper auto-detects

echo "voxscribe: model=$MODEL device=$DEV language=$LANGUAGE -> whisper" >&2
whisper "$AUDIO_IN" "${args[@]}"

# H-002: output-sanity guard (whisper exits 0 with empty/hallucinated text on non-speech)
TXT="$OUTDIR/$STEM.txt"; JSON="$OUTDIR/$STEM.json"; ok=1
{ [ -s "$TXT" ] && grep -q '[^[:space:]]' "$TXT"; } 2>/dev/null || ok=0
if [ -f "$JSON" ]; then
  segs="$(python3 -c "import json,sys;print(len(json.load(open(sys.argv[1])).get('segments',[])))" "$JSON" 2>/dev/null || echo 0)"
  [ "${segs:-0}" -gt 0 ] || ok=0
fi
if [ "$ok" -eq 0 ]; then
  echo "voxscribe: WARNING — empty/no-speech transcription (silent or non-speech input?). Files: $OUTDIR/$STEM.*" >&2
  exit 4
fi

echo "voxscribe: done. Output files in $OUTDIR:"
ls -1 "$OUTDIR/$STEM".* 2>/dev/null || true
echo "--- transcript ($STEM.txt) ---"
cat -- "$TXT"
```

- [ ] **Step 2 (H-009):** `chmod +x plugins/voxscribe/scripts/transcribe.sh` **ДО** `git add`,
  затем `git add` — git зафиксирует mode `100755`. Проверить: `git ls-files -s plugins/voxscribe/scripts/transcribe.sh`
  начинается с `100755`.
- [ ] **Step 3:** `bash -n` + (если есть) `shellcheck` → без ошибок.

---

### Task 3: SKILL.md

**Files:** Create `plugins/voxscribe/skills/voxscribe/SKILL.md`

- [ ] **Step 1:** Frontmatter + тело. `description` — с триггерами на RU и EN, охватывает аудио И видео:

```markdown
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
```

- [ ] **Step 2:** Проверить: нет mixed кириллица+латиница токенов в идентификаторах; frontmatter валиден (`---` обрамление).

---

### Task 4: references/options.md

**Files:** Create `plugins/voxscribe/skills/voxscribe/references/options.md`

- [ ] **Step 1:** Содержимое (ленивая подгрузка): таблица моделей (размер/VRAM/скорость/качество RU),
  device/VRAM-логика и почему `small` дефолт (medium ~5GB → OOM на 4GB GPU), language-коды и риск
  форса языка (H-003), советы по длинным файлам (`--model base/tiny`, `--keep-audio`),
  output-guard (exit 4), **установка** (`pipx install openai-whisper`, `apt/brew install ffmpeg`),
  **поддерживаемое окружение (H-005):** Linux + openai-whisper CLI; **known limitations:**
  macOS/whisper.cpp/faster-whisper НЕ поддержаны в v1 (preflight даст loud fail); заметка про
  возможный дрейф CLI-флагов openai-whisper между версиями. Текст — английский.

---

### Task 5: README — секция voxscribe

**Files:** Modify `README.md`

- [ ] **Step 1:** Добавить секцию про второй плагин voxscribe (что делает, install `/plugin install voxscribe`,
  пример `transcribe.sh interview.mp4`, ссылка на skill). Сохранить существующее содержание про research-pipeline.
  Если README структурирован под один плагин — аккуратно сделать «два плагина в маркетплейсе».

---

### Task 6: Тесты + install-верификация (verify-by-fact, урок BA-91)

- [ ] **Step 1: Манифесты** — `python3 -m json.tool` обоих → OK.
- [ ] **Step 2: Скрипт** — `bash -n` + `shellcheck` (если есть) → чисто.
- [ ] **Step 3: Smoke video-ветка** — сгенерировать крошечный mp4 с аудиодорожкой:
  `ffmpeg -nostdin -f lavfi -i sine=frequency=300:duration=3 -f lavfi -i color=c=black:s=128x128:d=3 -shortest -ac 1 -ar 16000 /tmp/vox_vid.mp4 -y`.
  Прогнать `transcribe.sh /tmp/vox_vid.mp4 --model tiny --out-dir /tmp/voxout`. Ожидание: ffmpeg-extract
  отработал; т.к. синус — речи нет → **exit 4 + WARNING** (H-002 guard срабатывает, durable-проверка). Создан `/tmp/voxout/vox_vid.json`.
- [ ] **Step 4: Smoke video-без-аудио** — `ffmpeg -f lavfi -i color=c=black:s=128x128:d=2 /tmp/vox_noaud.mp4 -y`
  → `transcribe.sh /tmp/vox_noaud.mp4` → **exit 3** «no audio stream».
- [ ] **Step 5: Реальная речь (если возможно)** — если в окружении есть TTS (`espeak-ng`/`say`) — синтезировать
  фразу в wav и прогнать: ожидание `.txt` непустой, `seo_applied`-аналог (exit 0). Если TTS нет — задокументировать
  в отчёте, что речевой positive-путь проверен только структурно (guard + форматы), и пометить как остаточный риск.
- [ ] **Step 6: Device-fallback (H-001)** — прогон с дефолтами НЕ падает OOM (в stderr либо `device=cuda` при влезании small, либо fallback `-> CPU`). Не torch.cuda.OutOfMemoryError.
- [ ] **Step 7: Install (H-004)** — задокументировать ручную проверку для пользователя:
  `/plugin marketplace add /home/serpens/Project/research-pipeline` → `/plugin install voxscribe` → рестарт →
  оба плагина (research-pipeline + voxscribe) доступны. (Агент не перезапускает свою сессию — оставить инструкцию.)
- [ ] **Step 8: Финальный fresh-eyes review** всей ветки + commit per задача.

---

## Self-Review

- **Spec coverage:** §3 размещение → Task 1; §4 transcribe.sh (preflight/детект/extract/device/language/guard) → Task 2;
  §5 SKILL → Task 3; §6 окружение/known-limitations → Task 4; §7 верификация → Task 6. H-001..H-005 покрыты (Task 2/1/4/6).
- **Placeholder scan:** конкретный код в Task 1/2/3; Task 4/5 — содержательные списки. Гэпов нет.
- **Type consistency:** STEM из оригинального input везде; exit-коды 1/2/3/4 согласованы spec↔script↔SKILL.
