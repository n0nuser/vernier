"""Distances, and the resolution limit that bounds what they can mean."""

from __future__ import annotations

import math

import pytest

from vernier.distance import (
    entropy,
    jsd,
    normalised_entropy,
    primary_metric,
    resolution_limit,
    tvd,
)
from vernier.types import HALF_QUANTUM, Reading


def noul(p: float) -> Reading:
    return Reading("noul", (("yes", p), ("no", 1.0 - p)), p, None)


def test_tvd_of_a_noul_pair_is_the_absolute_delta() -> None:
    assert tvd(noul(0.87).distribution, noul(0.89).distribution) == pytest.approx(0.02)


def test_identical_distributions_are_zero_apart() -> None:
    d = {"a": 0.5, "b": 0.3, "c": 0.2}
    assert tvd(d, d) == pytest.approx(0.0)
    assert jsd(d, d) == pytest.approx(0.0)


def test_jsd_is_symmetric_and_bounded() -> None:
    p, q = {"a": 1.0, "b": 0.0}, {"a": 0.0, "b": 1.0}
    assert jsd(p, q) == pytest.approx(jsd(q, p))
    assert jsd(p, q) == pytest.approx(1.0)


def test_jsd_never_exceeds_tvd() -> None:
    """The bound the resolution limit relies on to cover both metrics."""
    cases = [
        ({"a": 1.0, "b": 0.0}, {"a": 0.6, "b": 0.4}),
        ({"a": 0.5, "b": 0.3, "c": 0.2}, {"a": 0.2, "b": 0.3, "c": 0.5}),
        ({"a": 0.9, "b": 0.05, "c": 0.05}, {"a": 0.1, "b": 0.8, "c": 0.1}),
    ]
    for p, q in cases:
        assert jsd(p, q) <= tvd(p, q) + 1e-12


def test_distributions_are_normalised_before_comparison() -> None:
    """The API rounds each component alone, so a reported set can sum to 1.01."""
    raw = {"a": 0.69, "b": 0.16, "c": 0.16}
    assert sum(raw.values()) > 1.0
    assert tvd(raw, raw) == pytest.approx(0.0)
    assert tvd(raw, {k: v * 2 for k, v in raw.items()}) == pytest.approx(0.0)


def test_argmax_can_hold_still_while_the_distribution_moves() -> None:
    """The premise of the whole tool, stated as a test."""
    before = {"yes": 0.50, "no": 0.30, "unclear": 0.20}
    after = {"yes": 0.40, "no": 0.35, "unclear": 0.25}
    assert max(before, key=lambda k: before[k]) == max(after, key=lambda k: after[k])
    assert tvd(before, after) > 0.05
    assert jsd(before, after) > 0.0


def test_entropy_is_maximal_when_flat() -> None:
    assert entropy({"a": 0.5, "b": 0.5}) == pytest.approx(1.0)
    assert normalised_entropy({"a": 1 / 3, "b": 1 / 3, "c": 1 / 3}) == pytest.approx(1.0)
    assert normalised_entropy({"a": 1.0, "b": 0.0}) == pytest.approx(0.0)


def test_resolution_limit_is_never_zero() -> None:
    """Five identical one-hot readings mean jitter below the grid, not no jitter."""
    for n in (2, 3, 5):
        assert resolution_limit(n, "tvd") == pytest.approx(HALF_QUANTUM * n)
        assert resolution_limit(n, "jsd") > 0.0


def test_resolution_limit_covers_the_worst_rounding_case() -> None:
    """Two distributions that round alike can differ by a half step per component."""
    n = 3
    true_a = {"a": 0.5049, "b": 0.2951, "c": 0.2000}
    true_b = {"a": 0.4951, "b": 0.3049, "c": 0.2000}
    assert all(round(true_a[k], 2) == round(true_b[k], 2) for k in true_a)
    assert tvd(true_a, true_b) <= resolution_limit(n, "tvd") + 1e-12


def test_primary_metric_matches_the_question_type() -> None:
    assert primary_metric("noul") == "tvd"
    assert primary_metric("choice") == "jsd"
    assert primary_metric("score") == "jsd"


def test_unknown_metric_is_rejected() -> None:
    with pytest.raises(ValueError):
        resolution_limit(3, "cosine")


def test_entropy_of_a_degenerate_distribution_is_zero() -> None:
    assert entropy({"a": 1.0, "b": 0.0}) == pytest.approx(0.0)
    assert not math.isnan(entropy({"a": 0.0, "b": 0.0}))
