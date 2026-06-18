"""Golden tests for preprocess.py — paragraph stitching from segment-per-line.

If preprocess.py legitimately changes paragraph heuristic, update this test
explicitly — don't auto-update via --snapshot. The test guards the contract.
"""
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).parent.parent
FIXT = Path(__file__).parent / "fixtures"


def test_preprocess_stitches_into_one_paragraph(tmp_path):
    """Short input (<140 words) → single paragraph + H1 title."""
    src = FIXT / "preprocess_input.txt"
    work = tmp_path / "input.txt"
    shutil.copy(src, work)

    subprocess.run(
        [sys.executable, str(ROOT / "preprocess.py"), str(work)],
        check=True, capture_output=True,
    )
    md = (tmp_path / "input.md").read_text(encoding="utf-8")

    lines = md.splitlines()
    assert lines[0] == "# input", "first line must be the H1 derived from stem"
    assert lines[1] == "", "blank line after H1"
    body = "\n".join(lines[2:]).strip()
    paragraphs = [p for p in body.split("\n\n") if p.strip()]
    assert len(paragraphs) == 1, f"expected 1 paragraph for a 12-sentence input, got {len(paragraphs)}"
    assert "Дорогие друзья." in paragraphs[0]
    assert "интерпретирует традиция." in paragraphs[0]


def test_preprocess_paragraph_break_on_long_input(tmp_path):
    """Repeating fixture ×6 forces paragraph boundary at TARGET_PARAGRAPH_WORDS."""
    src_text = (FIXT / "preprocess_input.txt").read_text(encoding="utf-8")
    work = tmp_path / "long.txt"
    work.write_text(src_text * 6, encoding="utf-8")

    subprocess.run(
        [sys.executable, str(ROOT / "preprocess.py"), str(work)],
        check=True, capture_output=True,
    )
    md = (tmp_path / "long.md").read_text(encoding="utf-8")
    body = "\n".join(md.splitlines()[2:]).strip()
    paragraphs = [p for p in body.split("\n\n") if p.strip()]
    assert len(paragraphs) >= 2, "long input must produce multiple paragraphs"
    # Sanity: no paragraph blows past MAX_PARAGRAPH_WORDS by more than one sentence
    for p in paragraphs:
        assert len(p.split()) < 260, f"paragraph too long: {len(p.split())} words"


def test_preprocess_idempotent_skip(tmp_path):
    """Re-run without --force is a silent no-op when .md already exists."""
    src = FIXT / "preprocess_input.txt"
    work = tmp_path / "input.txt"
    shutil.copy(src, work)
    subprocess.run([sys.executable, str(ROOT / "preprocess.py"), str(work)], check=True)
    md_path = tmp_path / "input.md"
    first_mtime = md_path.stat().st_mtime
    # second run with no --force
    r = subprocess.run(
        [sys.executable, str(ROOT / "preprocess.py"), str(work)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
    assert "SKIP" in r.stderr
    assert md_path.stat().st_mtime == first_mtime, "must not rewrite without --force"
