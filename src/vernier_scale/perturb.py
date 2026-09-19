"""Perturbations: the two ways vernier removes a segment.

Deletion is the obvious move and a confound. Cutting text out shortens the
document, can orphan a heading and can break the grammar of what remains, and
all three move a probability for reasons that have nothing to do with the
segment's meaning. Masking holds length and shape roughly fixed and swaps only
the words, so the two modes disagree exactly where the confound bites.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence

from vernier_scale.filler import PLACEBO_SECTIONS, match_length, neutral_heading
from vernier_scale.types import Mode, Segment, SegmentKind

_HEADING_LINE = re.compile(r"^(#{1,6})[ \t]+.+$")
_BLANK_RUN = re.compile(r"\n{3,}")


def _tidy(text: str) -> str:
    """Collapse the blank-line pile-ups a deletion leaves behind.

    Without this, deleting a middle section leaves a four-newline gap that a
    model can see as damage. The same normalisation is applied to the baseline,
    so it can never be the thing that moves.
    """
    return _BLANK_RUN.sub("\n\n", text)


def _mask_heading(line: str) -> str:
    """Neutralise a heading while keeping its depth and any ordinal.

    Keeping the heading verbatim was the obvious thing and it was wrong: a
    section still titled "Our Standards" whose body is office trivia is
    incoherent, and a model can see that incoherence. Masking then measures the
    damage it did rather than the meaning it removed — a fresh confound in the
    very mode that exists to remove one.

    The ``#`` markers and a leading ordinal are structure, so they stay: the
    document keeps the same shape and the same numbered ladder. Only the words
    that carry meaning are swapped.
    """
    m = _HEADING_LINE.match(line)
    if m is None:
        return line
    marks = m.group(1)
    rest = line[len(marks) :].strip()
    ordinal = ""
    om = re.match(r"^(\d+[.)]\s*)", rest)
    if om:
        ordinal = om.group(1)
        rest = rest[len(ordinal) :]
    words = len(rest.split())
    return f"{marks} {ordinal}{neutral_heading(words)}".rstrip()


def _mask_text(body: str) -> str:
    """Length-matched neutral replacement for a segment.

    Word count, line shape, list markers and heading depth are preserved; every
    meaning-bearing word is replaced. What is left is a section of the same
    size and shape that says nothing about the question.
    """
    lines = body.split("\n")
    head = 0
    while head < len(lines) and not lines[head].strip():
        head += 1
    if head < len(lines) and _HEADING_LINE.match(lines[head]):
        kept = [*lines[:head], _mask_heading(lines[head])]
        rest = "\n".join(lines[head + 1 :])
        return "\n".join(kept) + ("\n" + match_length(rest) if lines[head + 1 :] else "")
    return match_length(body)


def render(segments: Sequence[Segment], omit: int | None = None, mode: Mode = Mode.DELETE) -> str:
    """Rebuild the document, with segment ``omit`` removed under ``mode``.

    ``omit=None`` renders the document unchanged; that rendering is what the
    baseline is measured on, so the baseline and every perturbed variant go
    through exactly the same code path.
    """
    parts: list[str] = []
    for seg in segments:
        if omit is not None and seg.index == omit:
            if mode is Mode.MASK:
                parts.append(_mask_text(seg.text))
            continue
        parts.append(seg.text)
    return _tidy("".join(parts))


def inject_placebos(
    segments: Sequence[Segment], count: int = len(PLACEBO_SECTIONS)
) -> list[Segment]:
    """Add neutral control sections to a segmented document.

    They are placed at fixed interior positions — roughly one third and two
    thirds of the way through — so they sit among real content rather than
    trailing off the end where a model may weight them less. Spans are
    renumbered to keep the tiling contract, but the offsets now describe the
    augmented document, not the original file.
    """
    real = list(segments)
    count = min(count, len(PLACEBO_SECTIONS))
    if count <= 0 or not real:
        return _renumber(real)
    depth = _common_depth(real)
    positions = sorted(
        {max(1, round(len(real) * (i + 1) / (count + 1))) for i in range(count)}
    )
    while len(positions) < count:  # tiny documents can collide; spread out
        positions.append(min(len(real), positions[-1] + 1))
    placebos = [
        Segment(
            index=-1,
            label=f"{'#' * depth} {title}",
            text=f"{'#' * depth} {title}\n\n{body}\n\n",
            start=-1,
            end=-1,
            kind=SegmentKind.PLACEBO,
        )
        for title, body in PLACEBO_SECTIONS[:count]
    ]
    out: list[Segment] = []
    for i, seg in enumerate(real):
        while placebos and positions and i == positions[0]:
            out.append(placebos.pop(0))
            positions.pop(0)
        out.append(seg)
    out.extend(placebos)
    return _renumber(out)


def _common_depth(segments: Sequence[Segment]) -> int:
    """The heading depth a placebo should wear to blend in.

    The modal depth, not the shallowest: a document has exactly one ``#`` title
    and a placebo wearing that depth would announce itself as a second title.
    """
    depths = [len(m.group(1)) for s in segments if (m := _HEADING_LINE.match(s.label))]
    return Counter(depths).most_common(1)[0][0] if depths else 2


def _renumber(segments: Sequence[Segment]) -> list[Segment]:
    """Reindex and re-span segments so they tile the document they now form."""
    out: list[Segment] = []
    cursor = 0
    for i, seg in enumerate(segments):
        out.append(
            Segment(
                index=i,
                label=seg.label,
                text=seg.text,
                start=cursor,
                end=cursor + len(seg.text),
                kind=seg.kind,
            )
        )
        cursor += len(seg.text)
    return out
