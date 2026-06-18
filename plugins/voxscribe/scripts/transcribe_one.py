#!/usr/bin/env python3
"""voxscribe — transcribe a single audio file via faster-whisper.

Writes <stem>.txt (raw segments, one per line) atomically (.partial → rename).
Also writes <stem>.segments.jsonl with per-segment timestamps for downstream
diarization/dialogue assembly. Idempotent: skips if <stem>.txt already exists
and is non-empty.

Designed for CPU (Tafsir default) but supports CUDA via --device.
"""
import argparse
import ctypes
import importlib.util
import json
import os
import sys
import time
from pathlib import Path


def _preload_cuda_libs():
    """Preload CUDA libs from pip-installed nvidia-* wheels so ctranslate2 finds them.

    No-op when nvidia-* wheels are not installed (the common CPU case).
    """
    for pkg in ("nvidia.cublas", "nvidia.cudnn"):
        spec = importlib.util.find_spec(pkg)
        if not spec or not spec.submodule_search_locations:
            continue
        lib_dir = Path(spec.submodule_search_locations[0]) / "lib"
        for so in lib_dir.glob("*.so*"):
            try:
                ctypes.CDLL(str(so), mode=ctypes.RTLD_GLOBAL)
            except OSError:
                pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", help="audio file path (any format faster-whisper accepts)")
    ap.add_argument("--out-dir", default=None, help="output directory (default: input's folder)")
    ap.add_argument("--model", default=os.environ.get("VOXSCRIBE_MODEL", "large-v3"))
    ap.add_argument("--device", default=os.environ.get("VOXSCRIBE_DEVICE", "cpu"),
                    choices=["cpu", "cuda", "auto"])
    ap.add_argument("--compute", default=os.environ.get("VOXSCRIBE_COMPUTE", "int8"),
                    help="ctranslate2 compute_type (int8, int8_float16, float16, float32)")
    ap.add_argument("--language", default=os.environ.get("VOXSCRIBE_LANGUAGE", "ru"),
                    help="ISO-639-1 code or 'auto' (default ru per Tafsir)")
    ap.add_argument("--beam-size", type=int, default=5)
    ap.add_argument("--no-vad", action="store_true", help="disable VAD filtering")
    ap.add_argument("--force", action="store_true", help="overwrite existing .txt")
    args = ap.parse_args()

    inp = Path(args.input)
    if not inp.is_file():
        print(f"voxscribe: input not found: {inp}", file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir) if args.out_dir else inp.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = inp.stem
    txt_path = out_dir / f"{stem}.txt"
    jsonl_path = out_dir / f"{stem}.segments.jsonl"

    if not args.force and txt_path.exists() and txt_path.stat().st_size > 0:
        print(f"voxscribe: SKIP {inp.name} ({txt_path.name} already exists)", file=sys.stderr)
        return 0

    _preload_cuda_libs()
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("voxscribe: faster-whisper not installed in this Python.\n"
              "  Install: pip install faster-whisper  (and for CPU int8 nothing else)\n"
              "  Tip: voxscribe auto-detects a project .venv at ./.venv; create one with:\n"
              "    python3 -m venv .venv && .venv/bin/pip install faster-whisper",
              file=sys.stderr)
        return 2

    language = None if args.language.lower() == "auto" else args.language
    print(f"voxscribe: loading model={args.model} device={args.device} compute={args.compute}",
          file=sys.stderr)
    model = WhisperModel(args.model, device=args.device, compute_type=args.compute)

    print(f"voxscribe: transcribing {inp.name}", file=sys.stderr)
    t0 = time.time()
    segments, info = model.transcribe(
        str(inp),
        language=language,
        vad_filter=not args.no_vad,
        beam_size=args.beam_size,
    )
    detected = info.language
    duration = info.duration
    print(f"voxscribe:   duration={duration:.1f}s detected={detected} "
          f"(p={info.language_probability:.2f})", file=sys.stderr)

    tmp_txt = txt_path.with_suffix(".txt.partial")
    tmp_jsonl = jsonl_path.with_suffix(".jsonl.partial")
    n_segments = 0
    next_progress = 60.0  # print a progress line for every minute of audio processed
    with open(tmp_txt, "w", encoding="utf-8") as ft, open(tmp_jsonl, "w", encoding="utf-8") as fj:
        for seg in segments:
            line = seg.text.strip()
            if not line:
                continue
            ft.write(line + "\n")
            ft.flush()
            fj.write(json.dumps({
                "start": round(seg.start, 3),
                "end": round(seg.end, 3),
                "text": line,
            }, ensure_ascii=False) + "\n")
            n_segments += 1
            # Progress: emit a line each time segment.start crosses the next minute mark
            while seg.start >= next_progress:
                pct = (next_progress / duration * 100) if duration else 0
                print(f"voxscribe:   [{next_progress:7.1f}/{duration:.1f}s, {pct:5.1f}%]", file=sys.stderr)
                next_progress += 60.0

    tmp_txt.replace(txt_path)
    tmp_jsonl.replace(jsonl_path)
    elapsed = time.time() - t0
    rtf = elapsed / duration if duration else 0
    print(f"voxscribe: saved {txt_path.name} ({n_segments} segments, "
          f"{elapsed:.1f}s wall, RTF={rtf:.2f})", file=sys.stderr)

    # H-002 sanity guard: empty / no-speech transcription
    if n_segments == 0 or txt_path.stat().st_size == 0:
        print(f"voxscribe: WARNING — empty / no-speech transcription for {inp.name}. "
              f"Silent input or wrong --language?", file=sys.stderr)
        return 4

    return 0


if __name__ == "__main__":
    sys.exit(main())
