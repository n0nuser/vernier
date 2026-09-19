"""Distances between distributions, and the resolution limit that bounds them.

The point of the whole tool is in this module's premise: a segment can reshape
a distribution without moving its argmax, so an argmax delta is the wrong
measurement. Total variation and Jensen-Shannon both see the reshaping.
"""

from __future__ import annotations

import math
from typing import Mapping, Sequence

from vernier.types import HALF_QUANTUM, Reading


def _normalise(p: Mapping[str, float]) -> dict[str, float]:
    """Rescale to sum to 1.

    The API rounds each component independently, so a reported distribution can
    sum to 1.01. The raw values are kept for reporting; the metrics work on the
    rescaled ones so a rounding artefact cannot masquerade as a difference.
    """
    total = sum(p.values())
    if total <= 0.0:
        return {k: 0.0 for k in p}
    return {k: v / total for k, v in p.items()}


def _aligned(p: Mapping[str, float], q: Mapping[str, float]) -> list[tuple[float, float]]:
    pn, qn = _normalise(p), _normalise(q)
    keys = sorted(set(pn) | set(qn))
    return [(pn.get(k, 0.0), qn.get(k, 0.0)) for k in keys]


def tvd(p: Mapping[str, float], q: Mapping[str, float]) -> float:
    """Total variation distance, in [0, 1].

    For a Noul's two-point distribution this is exactly ``|Δp|``, which is why
    it can serve as the one metric reported for every question type.
    """
    return 0.5 * sum(abs(a - b) for a, b in _aligned(p, q))


def jsd(p: Mapping[str, float], q: Mapping[str, float]) -> float:
    """Jensen-Shannon divergence in bits, in [0, 1].

    Symmetric, bounded, and finite even when an option has probability zero in
    one of the two distributions — which the 2dp rounding makes common.
    """
    total = 0.0
    for a, b in _aligned(p, q):
        m = 0.5 * (a + b)
        if m <= 0.0:
            continue
        if a > 0.0:
            total += 0.5 * a * math.log2(a / m)
        if b > 0.0:
            total += 0.5 * b * math.log2(b / m)
    return min(max(total, 0.0), 1.0)


def entropy(p: Mapping[str, float]) -> float:
    """Shannon entropy in bits."""
    return -sum(v * math.log2(v) for v in _normalise(p).values() if v > 0.0)


def normalised_entropy(p: Mapping[str, float]) -> float:
    """Entropy as a fraction of the maximum for this many outcomes, in [0, 1].

    This is the number ``haze`` reads: with well-formed options, 1.0 means the
    input does not decide the question.
    """
    n = len(p)
    if n < 2:
        return 0.0
    return entropy(p) / math.log2(n)


def distance(a: Reading, b: Reading, metric: str) -> float:
    if metric == "tvd":
        return tvd(a.distribution, b.distribution)
    if metric == "jsd":
        return jsd(a.distribution, b.distribution)
    raise ValueError(f"unknown metric {metric!r}")


def primary_metric(question_type: str) -> str:
    """The metric to rank on for a question type.

    A Noul has only one free parameter, so ``|Δp|`` — which is its TVD — says
    everything there is to say. Choice and Score have a whole distribution to
    move, so they get Jensen-Shannon.
    """
    return "tvd" if question_type == "noul" else "jsd"


def resolution_limit(support_size: int, metric: str) -> float:
    """The smallest distance that quantization alone can manufacture.

    Every probability comes back rounded to two decimals, so each reported
    component stands for a true value within ±0.005. Two genuinely different
    distributions can therefore round to the same output while differing by up
    to ``0.01`` per component, which bounds their TVD by ``0.005 * n``.

    Jensen-Shannon divergence in bits is bounded above by total variation
    distance, so the same number is a valid conservative floor for JSD.

    This is why a measured spread of zero is not a noise floor of zero: five
    identical one-hot readings tell you the jitter is below the grid, not that
    there is none.
    """
    if support_size < 2:
        raise ValueError("a distribution needs at least two outcomes")
    if metric not in {"tvd", "jsd"}:
        raise ValueError(f"unknown metric {metric!r}")
    return HALF_QUANTUM * support_size


def pairwise(readings: Sequence[Reading], metric: str) -> list[float]:
    """Every distinct pairwise distance among a set of readings."""
    out: list[float] = []
    for i in range(len(readings)):
        for j in range(i + 1, len(readings)):
            out.append(distance(readings[i], readings[j], metric))
    return out


def cross(a: Sequence[Reading], b: Sequence[Reading], metric: str) -> list[float]:
    """Every distance between one set of readings and another."""
    return [distance(x, y, metric) for x in a for y in b]
