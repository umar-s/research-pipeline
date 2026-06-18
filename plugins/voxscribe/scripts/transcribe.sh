#!/usr/bin/env bash
# voxscribe — transcribe audio/video to readable Russian text.
#
# Usage:
#   transcribe.sh <input> [options]
#
#   <input>  audio file (.mp3/.m4a/.wav/.flac/.ogg/.opus),
#            video file (.mp4/.mkv/.mov/.webm/.avi — audio is extracted via ffmpeg),
#            or a directory (prints the list of audio/video files and exits 0).
#
# Common options:
#   --mode {lecture|dialogue|raw}   default: lecture
#       lecture  = transcribe + paragraph-stitch into .md
#       dialogue = transcribe + pyannote diarization + sbert punctuation + .md
#       raw      = transcribe only (.txt + .segments.jsonl), no post-processing
#   --speakers "Кирилл,Тимур,Умар"  (dialogue mode) names assigned in descending
#                                   total-speech-time order
#   --model M       faster-whisper model (default: large-v3)
#   --device D      cpu|cuda|auto (default: cpu)
#   --compute C     ctranslate2 compute_type (default: int8)
#   --language L    ISO-639-1 or 'auto' (default: ru)
#   --out-dir O     output directory (default: input's folder)
#   --no-vad        disable VAD filtering
#   --keep-audio    keep the extracted wav (video inputs)
#   --force         overwrite existing outputs at every step
#
# Folder mode (idempotent):
#   When <input> is a directory, voxscribe lists candidate files as JSON on stdout
#   and exits. The skill instructs Claude to fan out parallel subagents — one per
#   file. The bash script itself never spawns transcribe processes in parallel.
#
# Exit codes:
#   0  success (or all-already-done in folder mode)
#   1  usage / input error
#   2  missing dependency
#   3  video without audio stream
#   4  empty / no-speech transcription
set -euo pipefail

die() { echo "voxscribe: $1" >&2; exit "${2:-1}"; }
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

MODE=lecture
ENGINE="${VOXSCRIBE_ENGINE:-faster-whisper}"
MODEL="${VOXSCRIBE_MODEL:-large-v3}"
DEVICE="${VOXSCRIBE_DEVICE:-cpu}"
COMPUTE="${VOXSCRIBE_COMPUTE:-int8}"
LANGUAGE="${VOXSCRIBE_LANGUAGE:-ru}"
OUTDIR=""
NO_VAD=0
KEEP_AUDIO=0
FORCE=0
SKIP_HF_PREFLIGHT=0
SPEAKERS=""
INPUT=""

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) sed -n '2,37p' "$0"; exit 0 ;;
    --mode) MODE="${2:?}"; shift 2 ;;
    --model) MODEL="${2:?}"; shift 2 ;;
    --device) DEVICE="${2:?}"; shift 2 ;;
    --compute) COMPUTE="${2:?}"; shift 2 ;;
    --language) LANGUAGE="${2:?}"; shift 2 ;;
    --out-dir) OUTDIR="${2:?}"; shift 2 ;;
    --speakers) SPEAKERS="${2:?}"; shift 2 ;;
    --no-vad) NO_VAD=1; shift ;;
    --keep-audio) KEEP_AUDIO=1; shift ;;
    --force) FORCE=1; shift ;;
    --skip-hf-preflight) SKIP_HF_PREFLIGHT=1; shift ;;
    --engine) ENGINE="${2:?}"; shift 2 ;;
    --) shift; break ;;
    -*) die "unknown option: $1" 1 ;;
    *) [ -z "$INPUT" ] && INPUT="$1" || die "unexpected arg: $1" 1; shift ;;
  esac
done
[ -n "$INPUT" ] || die "usage: transcribe.sh <input> [options]; --help for details" 1
case "$MODE" in lecture|dialogue|raw) ;; *) die "unknown --mode '$MODE'" 1 ;; esac
case "$ENGINE" in faster-whisper|whisperx) ;; *) die "unknown --engine '$ENGINE' (faster-whisper|whisperx)" 1 ;; esac

# Resolve a Python interpreter that has faster-whisper. Preference order:
#   1. $VOXSCRIBE_PYTHON
#   2. ./.venv/bin/python3 in the current directory (Tafsir convention)
#   3. ./.venv/bin/python3 in <input>'s directory's nearest ancestor
#   4. plain `python3` (must have faster-whisper installed)
detect_python() {
  if [ -n "${VOXSCRIBE_PYTHON:-}" ] && [ -x "$VOXSCRIBE_PYTHON" ]; then
    echo "$VOXSCRIBE_PYTHON"; return 0
  fi
  local dir
  for dir in "$PWD" "$(dirname -- "$INPUT")"; do
    local cur="$dir"
    while [ "$cur" != "/" ] && [ -n "$cur" ]; do
      if [ -x "$cur/.venv/bin/python3" ]; then
        echo "$cur/.venv/bin/python3"; return 0
      fi
      cur="$(dirname -- "$cur")"
    done
  done
  command -v python3 >/dev/null 2>&1 && { echo python3; return 0; }
  return 1
}

PY="$(detect_python || true)"
[ -n "$PY" ] || die "no python3 found (set \$VOXSCRIBE_PYTHON or create ./.venv with faster-whisper)" 2

# H-003: cheap RAM sanity check. Don't block — just warn — so non-Linux and
# memory-rich Linux boxes don't see noise. /proc/meminfo is Linux-only; on macOS
# this awk returns empty and we silently skip the check.
if [ -r /proc/meminfo ]; then
  mem_avail_kb="$(awk '/^MemAvailable:/ {print $2; exit}' /proc/meminfo 2>/dev/null || echo 0)"
  mem_avail_gb=$(( ${mem_avail_kb:-0} / 1024 / 1024 ))
  # large-v3 int8 wants ~3 GB; large-v3 fp16 wants ~5 GB; pyannote adds ~2 GB.
  threshold_gb=8
  [ "$MODE" = "dialogue" ] && threshold_gb=10
  if [ "$mem_avail_gb" -lt "$threshold_gb" ] && [ "$mem_avail_gb" -gt 0 ]; then
    echo "voxscribe: WARNING — only ${mem_avail_gb} GB RAM available, ${threshold_gb} GB recommended for $MODEL on --mode $MODE. Consider --model medium or --model small if this OOMs." >&2
  fi
fi

# Folder mode: emit JSON list of audio/video files and stop. The skill spawns
# subagents from this list — bash never parallelizes transcribe itself.
if [ -d "$INPUT" ]; then
  "$PY" -c "
import json, os, sys
from pathlib import Path
ROOT = Path(sys.argv[1])
AUDIO = {'.mp3','.m4a','.wav','.flac','.ogg','.opus'}
VIDEO = {'.mp4','.mkv','.mov','.webm','.avi','.m4v'}
items = []
for p in sorted(ROOT.iterdir()):
    if not p.is_file():
        continue
    ext = p.suffix.lower()
    if ext not in AUDIO and ext not in VIDEO:
        continue
    stem = p.stem
    md = p.with_suffix('.md')
    dialogue_md = p.with_name(stem + '.dialogue.md')
    has_md = md.exists() or dialogue_md.exists()
    items.append({
        'path': str(p),
        'name': p.name,
        'type': 'video' if ext in VIDEO else 'audio',
        'already_processed': has_md,
    })
print(json.dumps({'root': str(ROOT), 'files': items}, ensure_ascii=False, indent=2))
" "$INPUT"
  exit 0
fi

[ -f "$INPUT" ] && [ -r "$INPUT" ] || die "input not found/readable: $INPUT" 1
[ -n "$OUTDIR" ] || OUTDIR="$(dirname -- "$INPUT")"
mkdir -p -- "$OUTDIR"

# Preflight binaries needed for audio extraction + stream probing.
for bin in ffprobe ffmpeg; do
  command -v "$bin" >/dev/null 2>&1 || \
    die "'$bin' not found in PATH. Install: sudo apt install ffmpeg  (or: brew install ffmpeg)" 2
done

# H-002: dialogue mode fails fast on missing HF_TOKEN, invalid token, unaccepted
# terms, or missing pyannote/torch BEFORE the 60+ min transcription. Skip with
# --skip-hf-preflight when the pyannote model is already cached and offline.
if [ "$MODE" = "dialogue" ]; then
  # Always check that HF_TOKEN is set — even with --skip-hf-preflight, diarize
  # itself needs the token, and failing late is the whole bug H-002 fixed.
  [ -n "${HF_TOKEN:-}" ] || die "dialogue mode requires HF_TOKEN env var (pyannote)" 2
  if [ "$SKIP_HF_PREFLIGHT" -eq 0 ]; then
    "$PY" "$SCRIPT_DIR/hf_preflight.py" \
      --repo "${VOXSCRIBE_DIARIZATION_MODEL:-pyannote/speaker-diarization-community-1}"
  fi
fi

# Output basename always derived from the ORIGINAL input (not the temp wav).
in_base="$(basename -- "$INPUT")"; STEM="${in_base%.*}"

# H-008: a "real" video stream is one whose attached_pic disposition is 0.
# Cover-art / album-art in mp3/m4a is a video stream with attached_pic=1 and
# must be treated as audio (otherwise every tagged podcast mp3 wrongly goes
# through ffmpeg).
real_video="$(ffprobe -v error -select_streams v \
  -show_entries stream_disposition=attached_pic \
  -of csv=p=0 -- "$INPUT" 2>/dev/null | grep -c '^0$' || true)"

TMP_DIR=""
SLOT_FD=""
SLOT_PATH=""
# cleanup() runs on EXIT for ANY reason — die-paths, success, signals. It must
# return 0 unconditionally so the script's intended non-zero exit propagates,
# rather than being clobbered by a failed `rm` or release_slot.
cleanup() {
  release_slot 2>/dev/null || true
  if [ -n "$TMP_DIR" ] && [ "$KEEP_AUDIO" -eq 0 ]; then
    rm -rf -- "$TMP_DIR" || true
  fi
  return 0
}
trap cleanup EXIT

AUDIO_IN="$INPUT"
if [ "${real_video:-0}" -gt 0 ]; then
  has_audio="$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_type \
    -of csv=p=0 -- "$INPUT" 2>/dev/null || true)"
  [ -n "$has_audio" ] || die "video has no audio stream: $INPUT" 3
  TMP_DIR="$(mktemp -d)"
  AUDIO_IN="$TMP_DIR/$STEM.wav"
  echo "voxscribe: extracting audio from video via ffmpeg…" >&2
  ffmpeg -nostdin -v error -i "$INPUT" -vn -ac 1 -ar 16000 -c:a pcm_s16le -y -- "$AUDIO_IN"
fi

# H-001: CPU semaphore. When the skill fans out N parallel subagents on a folder,
# each call to this script tries to grab one of $MAX slots before launching the
# expensive transcription. The slot is held by an open FD; closing the FD (script
# exit or kill -9) releases it automatically — no stale-lock recovery needed.
MAX_CONCURRENT="${VOXSCRIBE_MAX_CONCURRENT:-2}"
# Validate: non-numeric values would crash `[ -le 0 ]` under set -e. Fall back to 2.
case "$MAX_CONCURRENT" in
  ''|*[!0-9]*) echo "voxscribe: WARN VOXSCRIBE_MAX_CONCURRENT='$MAX_CONCURRENT' is not numeric; using 2" >&2; MAX_CONCURRENT=2 ;;
esac
SLOT_FD=""
SLOT_PATH=""
acquire_slot() {
  [ "$MAX_CONCURRENT" -le 0 ] && return 0   # 0 disables the semaphore
  local lockdir="${TMPDIR:-/tmp}/voxscribe-cpu-slots"
  mkdir -p -- "$lockdir"
  local waited=0
  local max_wait=$(( ${VOXSCRIBE_SLOT_TIMEOUT:-86400} ))
  while true; do
    local i
    for i in $(seq 0 $((MAX_CONCURRENT - 1))); do
      local p="$lockdir/slot-$i.lock"
      exec {SLOT_FD}>"$p"
      if flock -n "$SLOT_FD"; then
        SLOT_PATH="$p"
        [ "$waited" -gt 0 ] && \
          echo "voxscribe: acquired CPU slot $i after ${waited}s wait" >&2
        return 0
      fi
      exec {SLOT_FD}>&-
      SLOT_FD=""
    done
    [ "$waited" -ge "$max_wait" ] && \
      die "all $MAX_CONCURRENT CPU slots busy after ${waited}s; raise VOXSCRIBE_MAX_CONCURRENT or wait" 1
    [ "$waited" -eq 0 ] && \
      echo "voxscribe: all $MAX_CONCURRENT CPU slots busy, waiting…" >&2
    sleep 5
    waited=$((waited + 5))
  done
}
release_slot() {
  if [ -n "$SLOT_FD" ]; then
    exec {SLOT_FD}>&-
    SLOT_FD=""
  fi
  return 0
}
# cleanup() is defined above (before `trap cleanup EXIT`) so it's safe even when
# ffmpeg / a die-call fires before this point — release_slot's stub is muzzled
# until acquire_slot has ever been called.

# H-004: optional WhisperX engine. WhisperX bundles faster-whisper + pyannote +
# forced alignment in one CLI; we just shell out to it. No integration with our
# diarize.py/dialogify.py — whisperx handles diarization internally. The user
# loses our sbert punctuation pass; gains tighter timestamp↔speaker alignment.
if [ "$ENGINE" = "whisperx" ]; then
  command -v whisperx >/dev/null 2>&1 || \
    die "--engine whisperx requires the 'whisperx' CLI. Install: pipx install whisperx (then visit https://github.com/m-bain/whisperX for diarization model gating)" 2
  if [ "$MODE" = "dialogue" ] && [ -z "${HF_TOKEN:-}" ]; then
    die "--engine whisperx --mode dialogue requires HF_TOKEN (pyannote diarization)" 2
  fi
  WX_ARGS=("$AUDIO_IN" "--model" "$MODEL"
           "--output_dir" "$OUTDIR" "--output_format" "all")
  # whisperx auto-detects language when --language is omitted
  [ "$LANGUAGE" != "auto" ] && WX_ARGS+=(--language "$LANGUAGE")
  case "$DEVICE" in
    cpu)  WX_ARGS+=(--device cpu --compute_type "$COMPUTE") ;;
    cuda) WX_ARGS+=(--device cuda) ;;
    auto) ;;  # let whisperx pick
    *)    die "unknown --device '$DEVICE' for whisperx (cpu|cuda|auto)" 1 ;;
  esac
  if [ "$MODE" = "dialogue" ]; then
    WX_ARGS+=(--diarize --hf_token "$HF_TOKEN")
  fi
  acquire_slot
  echo "voxscribe: invoking whisperx with model=$MODEL device=$DEVICE mode=$MODE" >&2
  whisperx "${WX_ARGS[@]}"
  echo "voxscribe: done (engine=whisperx). Output files in $OUTDIR:" >&2
  ls -1 "$OUTDIR/$STEM".* 2>/dev/null || true
  exit 0
fi

# Step 1: transcription (always). Output goes to OUTDIR with STEM.
TR_ARGS=("$SCRIPT_DIR/transcribe_one.py" "$AUDIO_IN" "--out-dir" "$OUTDIR"
         "--model" "$MODEL" "--device" "$DEVICE" "--compute" "$COMPUTE"
         "--language" "$LANGUAGE")
[ "$NO_VAD" -eq 1 ] && TR_ARGS+=(--no-vad)
[ "$FORCE" -eq 1 ] && TR_ARGS+=(--force)

# Acquire a CPU slot ONLY around the heavy steps. The slot is released when this
# script exits (cleanup trap closes the FD).
acquire_slot
set +e
"$PY" "${TR_ARGS[@]}"
tx_status=$?
set -e
if [ $tx_status -ne 0 ] && [ $tx_status -ne 4 ]; then
  exit $tx_status
fi
[ $tx_status -eq 4 ] && exit 4

# Step 2: post-processing per mode.
case "$MODE" in
  raw)
    : # nothing else
    ;;
  lecture)
    PP_ARGS=("$SCRIPT_DIR/preprocess.py" "$OUTDIR/$STEM.txt")
    [ "$FORCE" -eq 1 ] && PP_ARGS+=(--force)
    "$PY" "${PP_ARGS[@]}"
    ;;
  dialogue)
    DI_ARGS=("$SCRIPT_DIR/diarize.py" "$AUDIO_IN" "--out-dir" "$OUTDIR")
    [ "$FORCE" -eq 1 ] && DI_ARGS+=(--force)
    "$PY" "${DI_ARGS[@]}"
    DG_ARGS=("$SCRIPT_DIR/dialogify.py" "$OUTDIR/$STEM" "--punctuate")
    [ -n "$SPEAKERS" ] && DG_ARGS+=(--speakers "$SPEAKERS")
    [ "$FORCE" -eq 1 ] && DG_ARGS+=(--force)
    "$PY" "${DG_ARGS[@]}"
    ;;
esac

echo "voxscribe: done. Output files in $OUTDIR:" >&2
ls -1 "$OUTDIR/$STEM".* 2>/dev/null || true
