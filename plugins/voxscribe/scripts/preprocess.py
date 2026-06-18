#!/usr/bin/env python3
"""voxscribe — minimal post-processing of a faster-whisper .txt into .md.

Actions:
- stitches short per-segment lines into a single stream
- splits the stream into sentences at .!?…
- groups sentences into paragraphs of ~140 words (max 220)
- normalizes whitespace and pre-punctuation spacing
- does NOT remove filler words or rewrite phrases — that's an editorial pass

Output: <stem>.md next to <stem>.txt.
"""
import argparse
import re
import sys
from pathlib import Path

TARGET_PARAGRAPH_WORDS = 140
MAX_PARAGRAPH_WORDS = 220

SENTENCE_END = re.compile(r'[.!?…]["»)\]]?\s*$')
MULTI_SPACE = re.compile(r"[ \t]+")
PUNCT_SPACE_BEFORE = re.compile(r"\s+([,.;:!?…])")


def stitch_lines(text: str) -> str:
    parts = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return " ".join(parts)


def split_sentences(stream: str) -> list[str]:
    sentences = []
    buf = []
    for tok in stream.split(" "):
        buf.append(tok)
        if SENTENCE_END.search(tok):
            sentences.append(" ".join(buf).strip())
            buf = []
    if buf:
        sentences.append(" ".join(buf).strip())
    return [s for s in sentences if s]


def group_paragraphs(sentences: list[str]) -> list[str]:
    paragraphs, cur, cur_words = [], [], 0
    for s in sentences:
        w = len(s.split())
        if cur and (cur_words + w > MAX_PARAGRAPH_WORDS or
                    (cur_words >= TARGET_PARAGRAPH_WORDS and cur_words + w > TARGET_PARAGRAPH_WORDS)):
            paragraphs.append(" ".join(cur))
            cur, cur_words = [], 0
        cur.append(s)
        cur_words += w
    if cur:
        paragraphs.append(" ".join(cur))
    return paragraphs


def normalize(text: str) -> str:
    text = MULTI_SPACE.sub(" ", text)
    text = PUNCT_SPACE_BEFORE.sub(r"\1", text)
    return text.strip()


def process_file(txt_path: Path, out_md: Path | None = None) -> Path:
    raw = txt_path.read_text(encoding="utf-8")
    stream = stitch_lines(raw)
    sentences = split_sentences(stream)
    paragraphs = [normalize(p) for p in group_paragraphs(sentences)]
    title = txt_path.stem
    md = f"# {title}\n\n" + "\n\n".join(paragraphs) + "\n"
    out = out_md or txt_path.with_suffix(".md")
    out.write_text(md, encoding="utf-8")
    n_words = sum(len(p.split()) for p in paragraphs)
    print(f"voxscribe: {txt_path.name} -> {out.name}: "
          f"{len(paragraphs)} paragraphs, {n_words} words", file=sys.stderr)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", help="path to .txt produced by transcribe_one.py")
    ap.add_argument("--out", default=None, help="output .md path (default: <stem>.md)")
    ap.add_argument("--force", action="store_true", help="overwrite existing .md")
    args = ap.parse_args()

    p = Path(args.input)
    if not p.is_file():
        print(f"voxscribe: input not found: {p}", file=sys.stderr)
        return 1
    out = Path(args.out) if args.out else p.with_suffix(".md")
    if out.exists() and not args.force:
        print(f"voxscribe: SKIP preprocess ({out.name} already exists; --force to overwrite)",
              file=sys.stderr)
        return 0
    process_file(p, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
