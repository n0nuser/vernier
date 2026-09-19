"""Pluggable segmenters.

Every segmenter tiles the document exactly: the spans it returns are
contiguous, non-overlapping and cover the whole document. Verifying that is
the null-ablation control, done statically — if the segmenter cannot rebuild
the document byte-for-byte, any number it goes on to produce is measuring the
segmenter, not the text.
"""

from __future__ import annotations

import re
from typing import Callable, Sequence

from vernier.errors import VernierError
from vernier.types import Segment, SegmentKind

Segmenter = Callable[[str], list[Segment]]


class TilingError(VernierError, ValueError):
    """A segmenter produced spans that do not rebuild the document."""


def verify_tiling(text: str, segments: Sequence[Segment]) -> None:
    """Raise unless ``segments`` reconstruct ``text`` exactly."""
    cursor = 0
    for seg in segments:
        if seg.start != cursor:
            raise TilingError(
                f"segment {seg.index} ({seg.label!r}) starts at {seg.start}, expected {cursor}"
            )
        if seg.end < seg.start:
            raise TilingError(f"segment {seg.index} ({seg.label!r}) has end before start")
        if text[seg.start : seg.end] != seg.text:
            raise TilingError(f"segment {seg.index} ({seg.label!r}) text does not match its span")
        cursor = seg.end
    if cursor != len(text):
        raise TilingError(f"segments cover {cursor} of {len(text)} characters")
    if "".join(s.text for s in segments) != text:
        raise TilingError("concatenated segments do not reproduce the document")


def _build(text: str, bounds: Sequence[int], label: Callable[[str, int], str]) -> list[Segment]:
    """Turn a sorted list of cut points into tiling segments.

    ``bounds`` holds the start offset of each segment; the document's end
    closes the last one. Empty leading spans are dropped so a document that
    begins on a boundary does not open with a zero-length segment.
    """
    starts = [b for b in bounds if 0 <= b <= len(text)]
    if not starts or starts[0] != 0:
        starts = [0, *starts]
    starts = sorted(set(starts))
    segments: list[Segment] = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        body = text[start:end]
        if not body:
            continue
        idx = len(segments)
        segments.append(Segment(index=idx, label=label(body, idx), text=body, start=start, end=end))
    if not segments:
        segments.append(Segment(index=0, label="(empty document)", text="", start=0, end=0))
    return segments


def _summarise(body: str, limit: int = 56) -> str:
    """A one-line human label for a segment."""
    flat = " ".join(body.split())
    if not flat:
        return "(blank)"
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)
_FENCE = re.compile(r"^(?:```|~~~)", re.MULTILINE)


def _fenced_spans(text: str) -> list[tuple[int, int]]:
    """Character ranges inside fenced code blocks, where ``#`` is not a heading."""
    spans: list[tuple[int, int]] = []
    open_at: int | None = None
    for m in _FENCE.finditer(text):
        if open_at is None:
            open_at = m.start()
        else:
            spans.append((open_at, m.end()))
            open_at = None
    if open_at is not None:
        spans.append((open_at, len(text)))
    return spans


def markdown_sections(text: str) -> list[Segment]:
    """Split at every ATX heading. Each section carries its own heading.

    This is the segmentation that matters for a rulebook: a section is the unit
    an author wrote, edits and argues about, so it is the unit whose removal is
    worth a number.
    """
    fenced = _fenced_spans(text)

    def in_code(pos: int) -> bool:
        return any(lo <= pos < hi for lo, hi in fenced)

    bounds = [m.start() for m in _HEADING.finditer(text) if not in_code(m.start())]

    def label(body: str, _i: int) -> str:
        head = _HEADING.match(body.lstrip("\n"))
        if head:
            return f"{head.group(1)} {head.group(2)}"
        return f"(preamble) {_summarise(body)}"

    return _build(text, bounds, label)


_PARAGRAPH = re.compile(r"\n[ \t]*\n")


def paragraphs(text: str) -> list[Segment]:
    """Split on blank lines. Each paragraph keeps the whitespace that follows it."""
    bounds = [m.end() for m in _PARAGRAPH.finditer(text)]
    return _build(text, bounds, lambda body, _i: _summarise(body))


# A sentence ends at ., ? or ! followed by whitespace — unless the preceding
# token is a known abbreviation or a single initial, which would split a name.
_ABBREV = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc", "eg", "ie",
    "fig", "no", "inc", "ltd", "co", "approx", "al",
}
_SENTENCE_END = re.compile(r"(?<=[.!?])[\"')\]]*\s+")


def sentences(text: str) -> list[Segment]:
    """Split on sentence boundaries, with a short abbreviation guard."""
    bounds: list[int] = []
    for m in _SENTENCE_END.finditer(text):
        head = text[: m.start()].rstrip("\"')]")
        token = re.split(r"[\s(]", head)[-1].rstrip(".").lower()
        if token in _ABBREV or (len(token) == 1 and token.isalpha()):
            continue
        bounds.append(m.end())
    return _build(text, bounds, lambda body, _i: _summarise(body))


def lines(text: str) -> list[Segment]:
    """One segment per line, newline included."""
    bounds: list[int] = []
    pos = text.find("\n")
    while pos != -1:
        bounds.append(pos + 1)
        pos = text.find("\n", pos + 1)
    return _build(text, bounds, lambda body, _i: _summarise(body))


_LIST_ITEM = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+", re.MULTILINE)


def list_items(text: str) -> list[Segment]:
    """One segment per list item; text between lists rides along with what precedes it."""
    bounds = [m.start() for m in _LIST_ITEM.finditer(text)]
    return _build(text, bounds, lambda body, _i: _summarise(body))


SEGMENTERS: dict[str, Segmenter] = {
    "section": markdown_sections,
    "paragraph": paragraphs,
    "sentence": sentences,
    "line": lines,
    "item": list_items,
}


def segment(text: str, by: str) -> list[Segment]:
    """Segment ``text`` with the named segmenter, verifying the tiling."""
    try:
        segmenter = SEGMENTERS[by]
    except KeyError:
        known = ", ".join(sorted(SEGMENTERS))
        raise ValueError(f"unknown segmentation {by!r}; expected one of: {known}") from None
    segments = segmenter(text)
    verify_tiling(text, segments)
    return segments


def content_segments(segments: Sequence[Segment]) -> list[Segment]:
    return [s for s in segments if s.kind is SegmentKind.CONTENT]
