#!/usr/bin/env python3
"""voxscribe — run pyannote speaker diarization on an audio file.

Writes <stem>.diarization.json (exclusive speaker turns, no overlap) and a raw
serialization <stem>.diarization.raw.json. Idempotent.

Requires:
- pyannote.audio (4.x) installed in the active Python
- HF_TOKEN env var (read-token from huggingface.co)
- Accepted terms for pyannote/speaker-diarization-community-1 on HuggingFace
  (https://hf.co/pyannote/speaker-diarization-community-1)

CPU diarization of a 60-min file typically takes ~2–3 hours on a 6-core CPU.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", help="audio file (wav/mp3/m4a/...)")
    ap.add_argument("--out-dir", default=None, help="output dir (default: input's folder)")
    ap.add_argument("--model", default=os.environ.get(
        "VOXSCRIBE_DIARIZATION_MODEL", "pyannote/speaker-diarization-community-1"))
    ap.add_argument("--device", default=os.environ.get("VOXSCRIBE_DIARIZATION_DEVICE", "cpu"))
    ap.add_argument("--force", action="store_true", help="overwrite existing diarization.json")
    args = ap.parse_args()

    inp = Path(args.input)
    if not inp.is_file():
        print(f"voxscribe: input not found: {inp}", file=sys.stderr)
        return 1
    out_dir = Path(args.out_dir) if args.out_dir else inp.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = inp.stem
    out_json = out_dir / f"{stem}.diarization.json"
    out_raw = out_dir / f"{stem}.diarization.raw.json"

    if not args.force and out_json.exists() and out_json.stat().st_size > 0:
        print(f"voxscribe: SKIP diarize ({out_json.name} already exists)", file=sys.stderr)
        return 0

    token = os.environ.get("HF_TOKEN")
    if not token:
        print("voxscribe: HF_TOKEN not set. pyannote models are gated — create a read-token at\n"
              "  https://hf.co/settings/tokens\n"
              "and accept terms at https://hf.co/" + args.model, file=sys.stderr)
        return 2

    try:
        import torch
        from pyannote.audio import Pipeline
    except ImportError as e:
        print(f"voxscribe: pyannote.audio / torch not installed: {e}\n"
              "  Install (CPU): pip install 'pyannote.audio>=4' torch torchaudio "
              "--index-url https://download.pytorch.org/whl/cpu", file=sys.stderr)
        return 2

    print(f"voxscribe: loading {args.model}", file=sys.stderr)
    pipeline = Pipeline.from_pretrained(args.model, token=token)
    pipeline.to(torch.device(args.device))

    print(f"voxscribe: diarizing {inp.name} on {args.device} (this can take hours on CPU)…",
          file=sys.stderr)
    t0 = time.time()
    diarization = pipeline(str(inp))
    elapsed = time.time() - t0
    print(f"voxscribe: diarization done in {elapsed:.1f}s", file=sys.stderr)

    # H-style sanity: save the raw serialization FIRST so a downstream bug never
    # discards the expensive compute.
    try:
        raw = diarization.serialize()
        out_raw.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"voxscribe: raw -> {out_raw.name}", file=sys.stderr)
    except Exception as e:
        print(f"voxscribe: WARN serialize() failed: {e}", file=sys.stderr)
        raw = None

    # Prefer the "exclusive" turns (no overlap regions) for downstream dialogue assembly.
    if raw and "exclusive_diarization" in raw:
        turns = raw["exclusive_diarization"]
    else:
        turns = []
        for turn, _, speaker in diarization.exclusive_speaker_diarization.itertracks(yield_label=True):
            turns.append({
                "start": round(turn.start, 3),
                "end": round(turn.end, 3),
                "speaker": speaker,
            })

    out_json.write_text(json.dumps(turns, ensure_ascii=False, indent=2), encoding="utf-8")
    speakers = sorted({t["speaker"] for t in turns})
    print(f"voxscribe: saved {len(turns)} turns -> {out_json.name}; speakers={speakers}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
