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
    -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
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

TMP_DIR=""; cleanup() { [ -n "$TMP_DIR" ] && [ "$KEEP_AUDIO" -eq 0 ] && rm -rf -- "$TMP_DIR"; return 0; }
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
