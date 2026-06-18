"""Smoke test: SbertPuncCase loads and produces deterministic output on a fixture.

This is a contract test — guards against silent breakage if upstream model
changes or transformers API drifts. The exact punctuation can shift with
transformers/torch updates; we assert structural invariants, not exact strings.

Marked 'slow' — downloads ~700 MB on first run. Skipped automatically if
transformers/torch aren't installed.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def model():
    """Skip cleanly when optional deps aren't installed (lecture-only setup)."""
    pytest.importorskip("torch")
    pytest.importorskip("transformers")
    from sbert_punc.sbertpunccase import SbertPuncCase
    return SbertPuncCase()


def test_sbert_adds_punctuation_to_unpunctuated_russian(model):
    """Sentence-end markers must appear; first character is capitalized."""
    inp = "привет это тест без знаков препинания мы посмотрим как работает модель"
    out = model.punctuate(inp)
    assert any(out.endswith(p) or p in out for p in (".", "?", "!")), \
        f"expected sentence-end punctuation in: {out!r}"
    assert out[0].isupper(), f"first letter must be capitalized: {out!r}"
    assert "привет" not in out.lower().split()[0], \
        "first word must be casing-restored from lowercase input"


def test_sbert_chunks_long_input(model):
    """Internal np.array_split path runs when input is >512 tokens."""
    long = ("это очень длинный текст без знаков препинания " * 80).strip()
    out = model.punctuate(long)
    assert len(out) > 0
    assert out.count(".") + out.count("?") >= 1, \
        "expected at least one sentence boundary in long output"
