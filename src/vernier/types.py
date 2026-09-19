"""Value types shared across vernier's modules.

Everything here is frozen and free of I/O so that segmentation, perturbation,
the API client and the statistics can be tested in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal, Mapping

# The API reports every probability rounded to two decimal places. That is the
# instrument's resolution and it is the reason a measured spread of zero does
# not mean a noise floor of zero.
QUANTUM = 0.01
HALF_QUANTUM = QUANTUM / 2


class SegmentKind(str, Enum):
    """Where a segment came from."""

    CONTENT = "content"
    """Real text from the document under test."""

    PLACEBO = "placebo"
    """Neutral filler vernier injected itself, as a control condition."""


@dataclass(frozen=True, slots=True)
class Segment:
    """One unit of the document, addressed by a byte-exact span.

    A segmenter returns segments that tile the whole document with no gaps and
    no overlaps, so the document can be rebuilt by concatenating ``text``.
    """

    index: int
    label: str
    text: str
    start: int
    end: int
    kind: SegmentKind = SegmentKind.CONTENT

    @property
    def is_control(self) -> bool:
        return self.kind is SegmentKind.PLACEBO


class Mode(str, Enum):
    """How a segment is removed from the document."""

    DELETE = "delete"
    """Cut the segment out entirely. Changes the document's length."""

    MASK = "mask"
    """Replace it with length-matched neutral filler. Holds length roughly fixed."""


QuestionType = Literal["noul", "choice", "score"]


@dataclass(frozen=True, slots=True)
class Question:
    """A typed question, in the shape the System One API expects."""

    type: QuestionType
    instructions: str
    criteria: Mapping[str, str | None] | tuple[str, ...] | None = None

    def payload(self) -> dict[str, object]:
        body: dict[str, object] = {"type": self.type, "instructions": self.instructions}
        if self.criteria is not None:
            body["criteria"] = (
                list(self.criteria) if isinstance(self.criteria, tuple) else dict(self.criteria)
            )
        return body


@dataclass(frozen=True, slots=True)
class Reading:
    """One answer from Jev, normalised to a probability distribution.

    ``probs`` is the full distribution the whole tool is built to read: for a
    Noul it is the two-point distribution over yes/no, which the API gives as a
    single number.
    """

    type: QuestionType
    probs: tuple[tuple[str, float], ...]
    answer: str | float
    confidence: float | None

    @property
    def distribution(self) -> dict[str, float]:
        return dict(self.probs)

    @property
    def support(self) -> tuple[str, ...]:
        return tuple(k for k, _ in self.probs)

    @property
    def is_one_hot(self) -> bool:
        """True when the reported distribution puts all mass on one outcome.

        A one-hot baseline has no headroom: nothing can be measured moving
        except an outright flip, which is exactly what this tool exists to
        avoid relying on.
        """
        return any(abs(p - 1.0) < 1e-9 for _, p in self.probs)
