"""Perturbation: deletion removes, masking replaces without changing shape."""

from __future__ import annotations

import re

from vernier_scale.filler import filler_words, match_length, neutral_heading
from vernier_scale.perturb import inject_placebos, render
from vernier_scale.segment import segment, verify_tiling
from vernier_scale.types import Mode, SegmentKind

DOC = (
    "# Handbook\n\n"
    "## Alpha\n\nThe alpha rule applies to everyone without exception here.\n\n"
    "## Beta\n\nThe beta rule has three parts:\n\n- first part\n- second part\n\n"
    "## Gamma\n\nGamma is the final rule of the handbook.\n"
)


def test_render_unchanged_reproduces_the_document() -> None:
    segments = segment(DOC, "section")
    assert render(segments) == DOC


def test_delete_removes_the_segment_entirely() -> None:
    segments = segment(DOC, "section")
    out = render(segments, omit=1, mode=Mode.DELETE)
    assert "alpha rule" not in out
    assert "## Alpha" not in out
    assert "beta rule" in out


def test_mask_keeps_length_close_and_drops_the_meaning() -> None:
    segments = segment(DOC, "section")
    target = next(s for s in segments if s.label == "## Alpha")
    masked = render(segments, omit=target.index, mode=Mode.MASK)
    deleted = render(segments, omit=target.index, mode=Mode.DELETE)
    base = render(segments)
    assert "alpha rule" not in masked
    # Masking is much closer to the original length than deleting is.
    assert abs(len(masked) - len(base)) < abs(len(deleted) - len(base))


def test_mask_neutralises_the_heading_but_keeps_depth_and_ordinal() -> None:
    doc = "# T\n\n### 4. Permanent Ban\n\nA permanent ban from the community.\n"
    segments = segment(doc, "section")
    masked = render(segments, omit=1, mode=Mode.MASK)
    assert "Permanent Ban" not in masked
    # Depth and numbering are structure; they survive so the ladder keeps shape.
    assert re.search(r"^### 4\. \w+", masked, re.MULTILINE)


def test_mask_preserves_word_count_and_list_markers() -> None:
    source = "The beta rule has parts:\n\n- first part here\n- second part here\n"
    out = match_length(source)
    assert len(out.split("\n")) == len(source.split("\n"))
    for a, b in zip(source.split("\n"), out.split("\n"), strict=True):
        assert len(a.split()) == len(b.split())
    assert out.count("- ") == source.count("- ")


def test_filler_is_deterministic_and_sized() -> None:
    assert filler_words(7) == filler_words(7)
    assert len(filler_words(7)) == 7
    assert filler_words(0) == []
    assert neutral_heading(3).count(" ") == 2


def test_deletion_does_not_leave_blank_line_pileups() -> None:
    segments = segment(DOC, "section")
    for i in range(len(segments)):
        assert "\n\n\n" not in render(segments, omit=i, mode=Mode.DELETE)


def test_placebos_are_injected_inside_the_document_and_still_tile() -> None:
    segments = inject_placebos(segment(DOC, "section"), 2)
    controls = [s for s in segments if s.kind is SegmentKind.PLACEBO]
    assert len(controls) == 2
    # Not all at the end: a control that trails off the document is a weak control.
    assert controls[0].index < len(segments) - 1
    verify_tiling(render(segments), segments)


def test_placebos_wear_the_modal_heading_depth() -> None:
    segments = inject_placebos(segment(DOC, "section"), 2)
    controls = [s for s in segments if s.kind is SegmentKind.PLACEBO]
    assert all(s.label.startswith("## ") for s in controls)


def test_placebo_text_says_nothing_about_the_document() -> None:
    segments = inject_placebos(segment(DOC, "section"), 2)
    controls = [s for s in segments if s.kind is SegmentKind.PLACEBO]
    for c in controls:
        assert "rule" not in c.text.lower()
