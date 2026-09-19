"""Constructors for the three question types.

These mirror the helpers TypeSafe's own SDKs expose, so a question written
against the vendor's documentation transfers here unchanged. Question itself
stays available for anyone who would rather build the record directly.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from vernier.errors import VernierError
from vernier.types import Question


class QuestionError(VernierError, ValueError):
    """A question was built in a shape the API cannot answer."""


def noul(instructions: str, *, true: str | None = None, false: str | None = None) -> Question:
    """A yes/no question, answered as the probability that the answer is yes.

    Phrase it so that a high probability means yes. The optional true and false
    descriptions pin down what each outcome means when the boundary is subtle.

    Args:
        instructions: The yes/no question, or a statement to judge for truth.
        true: What a yes means.
        false: What a no means.

    Raises:
        QuestionError: If instructions are empty.
    """
    _require_text(instructions)
    criteria = {k: v for k, v in (("true", true), ("false", false)) if v is not None}
    return Question("noul", instructions, criteria or None)


def choice(instructions: str, options: Mapping[str, str | None] | Sequence[str]) -> Question:
    """Pick one option from a set, answered as a probability for every option.

    Args:
        instructions: What the model should decide.
        options: Either option names, or names mapped to a rubric description.

    Raises:
        QuestionError: If fewer than two distinct options are given.
    """
    _require_text(instructions)
    if isinstance(options, Mapping):
        criteria: dict[str, str | None] = dict(options)
    else:
        names = list(options)
        if len(set(names)) != len(names):
            raise QuestionError("choice options must be distinct")
        criteria = dict.fromkeys(names)
    if len(criteria) < 2:
        raise QuestionError("a choice needs at least two distinct options")
    return Question("choice", instructions, criteria)


def score(instructions: str, levels: Sequence[str]) -> Question:
    """Rate against ordered levels, answered as a probability for every level.

    Args:
        instructions: What the model should rate.
        levels: The level descriptions, lowest first.

    Raises:
        QuestionError: If fewer than two levels are given.
    """
    _require_text(instructions)
    ordered = tuple(levels)
    if len(ordered) < 2:
        raise QuestionError("a score needs at least two levels, lowest first")
    return Question("score", instructions, ordered)


def from_mapping(spec: Mapping[str, object]) -> Question:
    """Build a question from a decoded JSON spec.

    Raises:
        QuestionError: If the spec is missing a type or instructions, or names
            a type that does not exist.
    """
    kind = spec.get("type")
    instructions = spec.get("instructions")
    if not isinstance(instructions, str):
        raise QuestionError("a question spec needs 'instructions' as a string")
    criteria = spec.get("criteria")
    if kind == "noul":
        pairs = criteria if isinstance(criteria, Mapping) else {}
        return noul(
            instructions,
            true=_optional_text(pairs.get("true")),
            false=_optional_text(pairs.get("false")),
        )
    if kind == "choice":
        if not isinstance(criteria, Mapping):
            raise QuestionError("a choice spec needs 'criteria' as an object of options")
        return choice(instructions, {str(k): _optional_text(v) for k, v in criteria.items()})
    if kind == "score":
        if not isinstance(criteria, Sequence) or isinstance(criteria, str):
            raise QuestionError("a score spec needs 'criteria' as an array of levels")
        return score(instructions, [str(level) for level in criteria])
    raise QuestionError(f"unknown question type {kind!r}; expected noul, choice or score")


def _require_text(instructions: str) -> None:
    if not instructions.strip():
        raise QuestionError("a question needs instructions")


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) else None
