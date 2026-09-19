"""A fixed corpus of neutral filler text.

Two jobs, both of which must be deterministic and network-free so the test
suite can assert on them:

* **Masking.** Replacing a segment with length-matched filler separates "this
  text mattered" from "this document got shorter and lumpier".
* **Placebo segments.** Text injected into the document that cannot bear on any
  sensible question about it. If ablating a placebo moves the number, the
  instrument is not measuring meaning and vernier says so instead of ranking.

The sentences are deliberately bland, grammatical and from an unrelated domain
(facilities and office housekeeping). Nonsense would be its own signal: a model
can notice that a document has been vandalised, and that noticing is not the
effect we are trying to measure.
"""

from __future__ import annotations

import re

FILLER_SENTENCES: tuple[str, ...] = (
    "The building's main entrance is on the north side of the courtyard.",
    "Recycling bins are collected on the first Tuesday of each month.",
    "Visitors may leave bicycles in the covered rack beside the loading bay.",
    "The stationery cupboard is restocked at the end of every quarter.",
    "Meeting rooms can be booked through the shared calendar in the usual way.",
    "The kettle in the second-floor kitchen was replaced last spring.",
    "Parking permits are printed on blue card and expire at the end of the year.",
    "Window cleaning takes place twice a year, weather permitting.",
    "The noticeboard by the stairwell is cleared of old items each September.",
    "Deliveries arriving after five o'clock are held at the reception desk.",
)

PLACEBO_SECTIONS: tuple[tuple[str, str], ...] = (
    (
        "Building Access",
        "The building's main entrance is on the north side of the courtyard. "
        "Visitors may leave bicycles in the covered rack beside the loading bay. "
        "Deliveries arriving after five o'clock are held at the reception desk.",
    ),
    (
        "Facilities Housekeeping",
        "Recycling bins are collected on the first Tuesday of each month. "
        "The stationery cupboard is restocked at the end of every quarter. "
        "Window cleaning takes place twice a year, weather permitting.",
    ),
)
"""Neutral sections injected as the control condition, with their headings."""


def filler_words(count: int) -> list[str]:
    """``count`` words drawn in order from the filler corpus, cycling as needed."""
    if count <= 0:
        return []
    out: list[str] = []
    i = 0
    while len(out) < count:
        out.extend(FILLER_SENTENCES[i % len(FILLER_SENTENCES)].split())
        i += 1
    out = out[:count]
    # Keep the run grammatical at the seam: the truncated tail gets a full stop
    # and the opening word stays capitalised.
    tail = out[-1].rstrip(".,;:")
    out[-1] = tail + "."
    return out


_WORD = re.compile(r"\S+")


def match_length(source: str) -> str:
    """Neutral filler with the same word count and line shape as ``source``.

    Word count, line count and per-line word counts are preserved, so a masked
    document has very nearly the same length and layout as the original. Markdown
    list markers and blockquote markers are kept, because dropping them would
    change the document's structure as well as its words.
    """
    out_lines: list[str] = []
    budget_cursor = 0
    total = sum(len(_WORD.findall(line)) for line in source.split("\n"))
    pool = filler_words(total)
    for line in source.split("\n"):
        marker_match = re.match(r"^([ \t]*(?:[-*+]|\d+[.)]|>)[ \t]+)", line)
        marker = marker_match.group(1) if marker_match else ""
        body = line[len(marker) :]
        n = len(_WORD.findall(body))
        if n == 0:
            out_lines.append(marker.rstrip() if marker else "")
            continue
        indent_match = re.match(r"^[ \t]*", body)
        indent = indent_match.group(0) if indent_match and not marker else ""
        words = pool[budget_cursor : budget_cursor + n]
        budget_cursor += n
        out_lines.append(f"{marker}{indent}{' '.join(words)}")
    return "\n".join(out_lines)


HEADING_WORDS: tuple[str, ...] = (
    "General",
    "Notes",
    "Additional",
    "Information",
    "Supplementary",
    "Details",
    "Background",
    "Reference",
    "Remarks",
    "Overview",
)


def neutral_heading(count: int) -> str:
    """``count`` neutral heading words, for masking a heading's text."""
    if count <= 0:
        return ""
    return " ".join(HEADING_WORDS[i % len(HEADING_WORDS)] for i in range(count))
