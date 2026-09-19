"""Segmenters must tile the document exactly — that is the null-ablation control."""

from __future__ import annotations

from pathlib import Path

import pytest

from vernier_scale.segment import SEGMENTERS, TilingError, segment, verify_tiling
from vernier_scale.types import Segment

RULEBOOK = Path(__file__).resolve().parents[1] / "examples" / "contributor-covenant-2.1.md"

SAMPLES = [
    "",
    "one line",
    "# Title\n\nBody text.\n",
    "No headings here. Just two sentences.\n",
    "# A\n\nalpha\n\n## B\n\nbeta\n\n### C\n\n- one\n- two\n",
    "Dr. Smith met Mrs. Jones at 3 p.m. Then they left.\n",
    "\n\n\n",
    "# H\n\n```\n# not a heading\n```\n\n## Real\n\ntext\n",
]


@pytest.mark.parametrize("name", sorted(SEGMENTERS))
@pytest.mark.parametrize("text", SAMPLES)
def test_every_segmenter_tiles_exactly(name: str, text: str) -> None:
    segments = segment(text, name)
    verify_tiling(text, segments)
    assert "".join(s.text for s in segments) == text


@pytest.mark.parametrize("name", sorted(SEGMENTERS))
def test_every_segmenter_tiles_the_real_rulebook(name: str) -> None:
    text = RULEBOOK.read_text(encoding="utf-8")
    segments = segment(text, name)
    verify_tiling(text, segments)
    assert len(segments) > 1


def test_markdown_sections_split_at_headings() -> None:
    text = RULEBOOK.read_text(encoding="utf-8")
    labels = [s.label for s in segment(text, "section")]
    assert labels[0] == "# Contributor Covenant Code of Conduct"
    assert "### 4. Permanent Ban" in labels
    assert "## Attribution" in labels


def test_headings_inside_code_fences_are_not_headings() -> None:
    text = "# Real\n\n```\n# fake\n```\n\n## Also real\n\nx\n"
    labels = [s.label for s in segment(text, "section")]
    assert labels == ["# Real", "## Also real"]


def test_abbreviations_do_not_split_sentences() -> None:
    text = "Dr. Smith arrived. He waited."
    assert len(segment(text, "sentence")) == 2


def test_unknown_segmenter_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown segmentation"):
        segment("x", "sonnets")


def test_verify_tiling_catches_a_gap() -> None:
    bad = [Segment(0, "a", "ab", 0, 2), Segment(1, "b", "de", 3, 5)]
    with pytest.raises(TilingError):
        verify_tiling("abcde", bad)


def test_verify_tiling_catches_short_coverage() -> None:
    with pytest.raises(TilingError, match="cover"):
        verify_tiling("abcde", [Segment(0, "a", "abc", 0, 3)])


def test_verify_tiling_catches_text_span_mismatch() -> None:
    with pytest.raises(TilingError, match="does not match"):
        verify_tiling("abcde", [Segment(0, "a", "xxxxx", 0, 5)])
