#!/usr/bin/env python3
"""voxscribe — assemble a dialogue .md from transcription + diarization.

Inputs (auto-derived from <audio> path):
  <stem>.segments.jsonl   — from transcribe_one.py (per-segment timestamps + text)
  <stem>.diarization.json — from diarize.py (exclusive speaker turns)

Output:
  <stem>.dialogue.md      — markdown with speaker labels and em-dash dialogue,
                            optionally with restored punctuation (sbert).

Speaker → name mapping (--speakers): comma-separated names, applied in order of
total speech time descending (most-speaking → first name). If fewer names than
speakers, remaining speakers keep their SPEAKER_XX labels.
"""
import argparse
import bisect
import json
import os
import re
import sys
from pathlib import Path

PUNCT_FIX_BEFORE = re.compile(r"\s+([,.;:!?…])")
MULTI_SPACE = re.compile(r"[ \t]+")
MULTI_DOT = re.compile(r"\.{4,}")


def load_segments(path: Path) -> list[dict]:
    segs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        segs.append(json.loads(line))
    return segs


def assign_speakers(segments: list[dict], turns: list[dict]) -> None:
    """Assign each whisper segment a speaker by max temporal overlap with diarization."""
    by_start = sorted(turns, key=lambda t: t["start"])
    starts = [t["start"] for t in by_start]
    for seg in segments:
        s, e = seg["start"], seg["end"]
        i_lo = max(0, bisect.bisect_right(starts, s) - 1)
        best_speaker, best_overlap = None, 0.0
        for j in range(i_lo, len(by_start)):
            t = by_start[j]
            if t["start"] >= e:
                break
            ov = max(0.0, min(e, t["end"]) - max(s, t["start"]))
            if ov > best_overlap:
                best_overlap, best_speaker = ov, t["speaker"]
        if best_speaker is None:
            center = (s + e) / 2
            best_d = float("inf")
            for t in by_start:
                d = max(0.0, max(t["start"] - center, center - t["end"]))
                if d < best_d:
                    best_d, best_speaker = d, t["speaker"]
        seg["speaker"] = best_speaker or "UNKNOWN"


def group_turns(segments: list[dict]) -> list[dict]:
    """Merge consecutive same-speaker segments into one turn."""
    turns, cur = [], None
    for s in segments:
        if cur is None or s["speaker"] != cur["speaker"]:
            if cur:
                turns.append(cur)
            cur = {"speaker": s["speaker"], "start": s["start"], "end": s["end"], "parts": [s["text"]]}
        else:
            cur["end"] = s["end"]
            cur["parts"].append(s["text"])
    if cur:
        turns.append(cur)
    for t in turns:
        t["text"] = " ".join(p for p in t["parts"] if p).strip()
    return turns


def strip_punct_for_sbert(text: str) -> str:
    """sbert_punc_case_ru was trained on plain lowercase space-separated tokens.
    Em-dash / dash artifacts from whisper's punctuation pass measurably hurt
    its predictions — strip them along with sentence punctuation.
    """
    text = text.lower()
    text = re.sub(r"[.,!?;:…\"«»()\[\]—–-]+", " ", text)
    text = MULTI_SPACE.sub(" ", text).strip()
    return text


def normalize(text: str) -> str:
    text = MULTI_SPACE.sub(" ", text)
    text = PUNCT_FIX_BEFORE.sub(r"\1", text)
    text = MULTI_DOT.sub("…", text)
    return text.strip()


def chunked_words(words: list[str], max_words: int = 90):
    for i in range(0, len(words), max_words):
        yield words[i : i + max_words]


def punctuate_long(model, text: str) -> str:
    if not text:
        return text
    pieces = []
    for chunk in chunked_words(text.split(), 90):
        pieces.append(model.punctuate(" ".join(chunk)))
    return " ".join(pieces)


def label_speakers(turns_diar: list[dict], names: list[str]) -> dict[str, str]:
    """Map SPEAKER_XX -> human name by total speech time (descending)."""
    totals: dict[str, float] = {}
    for d in turns_diar:
        totals[d["speaker"]] = totals.get(d["speaker"], 0) + (d["end"] - d["start"])
    by_total = sorted(totals.items(), key=lambda x: -x[1])
    labels: dict[str, str] = {}
    for i, (sp, _) in enumerate(by_total):
        if i < len(names):
            labels[sp] = names[i].strip()
        else:
            labels[sp] = sp
    return labels


def format_dialogue(turns: list[dict], labels: dict[str, str], paragraph_word_limit: int) -> str:
    lines = ["# Dialogue", ""]
    for t in turns:
        name = labels.get(t["speaker"], t["speaker"])
        text = t["text"].strip()
        if not text:
            continue
        if paragraph_word_limit and len(text.split()) > paragraph_word_limit:
            sentences = re.split(r"(?<=[.!?…])\s+", text)
            paragraphs, cur, cw = [], [], 0
            for s in sentences:
                w = len(s.split())
                if cur and cw + w > paragraph_word_limit:
                    paragraphs.append(" ".join(cur))
                    cur, cw = [], 0
                cur.append(s)
                cw += w
            if cur:
                paragraphs.append(" ".join(cur))
            joined = "\n\n".join(paragraphs)
            lines.append(f"**{name}.**\n\n— {joined}")
        else:
            lines.append(f"**{name}.** — {text}")
    return "\n\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", help="audio file (used to derive <stem>.segments.jsonl + <stem>.diarization.json paths)")
    ap.add_argument("--out", default=None, help="output .md (default: <stem>.dialogue.md)")
    ap.add_argument("--speakers", default="", help="comma-separated names (most-speaking first)")
    ap.add_argument("--punctuate", action="store_true",
                    help="restore punctuation per turn via sbert_punc_case_ru (Russian only)")
    ap.add_argument("--paragraph-words", type=int, default=100,
                    help="split long turns into paragraphs at sentence boundaries near N words")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    inp = Path(args.input)
    stem = inp.stem
    base = inp.parent

    segs_path = base / f"{stem}.segments.jsonl"
    diar_path = base / f"{stem}.diarization.json"
    out_path = Path(args.out) if args.out else base / f"{stem}.dialogue.md"

    if not segs_path.is_file():
        print(f"voxscribe: missing segments file: {segs_path} (run transcribe_one.py first)",
              file=sys.stderr)
        return 1
    if not diar_path.is_file():
        print(f"voxscribe: missing diarization: {diar_path} (run diarize.py first)",
              file=sys.stderr)
        return 1
    if out_path.exists() and not args.force:
        print(f"voxscribe: SKIP dialogify ({out_path.name} already exists; --force to overwrite)",
              file=sys.stderr)
        return 0

    segs = load_segments(segs_path)
    turns_diar = json.loads(diar_path.read_text(encoding="utf-8"))
    print(f"voxscribe: {len(segs)} segments, {len(turns_diar)} diarization turns", file=sys.stderr)

    assign_speakers(segs, turns_diar)
    turns = group_turns(segs)
    print(f"voxscribe: {len(turns)} merged dialog turns", file=sys.stderr)

    names = [n for n in args.speakers.split(",") if n.strip()] if args.speakers else []
    labels = label_speakers(turns_diar, names)
    print(f"voxscribe: speaker labels: {labels}", file=sys.stderr)

    if args.punctuate:
        try:
            from sbert_punc.sbertpunccase import SbertPuncCase
        except ImportError:
            print("voxscribe: sbert_punc bundle not found next to this script.\n"
                  "  Expected: scripts/sbert_punc/sbertpunccase.py", file=sys.stderr)
            return 2
        try:
            from transformers import AutoModelForTokenClassification  # noqa: F401
        except ImportError:
            print("voxscribe: transformers not installed.\n"
                  "  Install: pip install transformers", file=sys.stderr)
            return 2
        print("voxscribe: loading sbert_punc_case_ru…", file=sys.stderr)
        model = SbertPuncCase()
        for i, t in enumerate(turns):
            raw = strip_punct_for_sbert(t["text"])
            if not raw:
                t["text"] = ""
                continue
            try:
                t["text"] = normalize(punctuate_long(model, raw))
            except Exception as e:
                print(f"voxscribe: WARN sbert turn {i}: {e}", file=sys.stderr)
                t["text"] = normalize(t["text"])
            if (i + 1) % 25 == 0:
                print(f"voxscribe:   sbert {i + 1}/{len(turns)}", file=sys.stderr)

    md = format_dialogue(turns, labels, args.paragraph_words)
    out_path.write_text(md, encoding="utf-8")
    print(f"voxscribe: saved {out_path.name}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    # Make `from sbert_punc.sbertpunccase import SbertPuncCase` work when bundled.
    sys.path.insert(0, str(Path(__file__).parent))
    sys.exit(main())
