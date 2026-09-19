"""The noise floor and the two hurdles a finding has to clear."""

from __future__ import annotations

import pytest

from vernier_scale.noise import (
    ALPHA,
    Verdict,
    classify,
    failed_effect,
    measure_effect,
    measure_noise_floor,
    mean_distribution,
    permutation_p,
    rank_key,
)
from vernier_scale.types import Reading


def noul(p: float) -> Reading:
    return Reading("noul", (("yes", p), ("no", round(1.0 - p, 2))), p, None)


def one_hot() -> Reading:
    return Reading("choice", (("a", 1.0), ("b", 0.0), ("c", 0.0)), "a", 1.0)


BASE = [noul(0.80), noul(0.81), noul(0.81), noul(0.81), noul(0.81)]


def test_floor_is_never_zero_even_when_the_spread_is() -> None:
    """The failure mode: identical readings must not licence ranking everything."""
    floor = measure_noise_floor([noul(0.81)] * 5, "tvd")
    assert floor.observed == 0.0
    assert floor.value > 0.0
    assert floor.limited_by == "quantization"


def test_a_saturated_baseline_is_flagged_at_the_resolution_limit() -> None:
    floor = measure_noise_floor([one_hot()] * 5, "jsd")
    assert floor.saturated
    assert floor.at_resolution_limit
    assert floor.value > 0.0


def test_a_moving_baseline_is_not_at_the_resolution_limit() -> None:
    floor = measure_noise_floor(BASE, "tvd")
    assert not floor.at_resolution_limit
    assert floor.observed == pytest.approx(0.01)


def test_threshold_sits_one_resolution_step_above_the_floor() -> None:
    floor = measure_noise_floor(BASE, "tvd")
    assert floor.threshold == pytest.approx(floor.value + floor.quantization)


def test_a_floor_needs_at_least_two_replicates() -> None:
    with pytest.raises(ValueError):
        measure_noise_floor([noul(0.5)], "tvd")


def test_a_large_repeatable_effect_clears_both_hurdles() -> None:
    floor = measure_noise_floor(BASE, "tvd")
    effect = measure_effect(BASE, [noul(0.61), noul(0.62), noul(0.60)], "tvd")
    assert effect.size == pytest.approx(0.198, abs=0.01)
    assert effect.p_value <= ALPHA
    assert effect.clears(floor)
    assert effect.direction < 0


def test_a_tiny_but_perfectly_repeatable_effect_is_rejected_on_size() -> None:
    """Statistical significance is not enough: the move must also matter."""
    floor = measure_noise_floor(BASE, "tvd")
    effect = measure_effect(BASE, [noul(0.82), noul(0.83), noul(0.82)], "tvd")
    assert effect.p_value <= ALPHA
    assert effect.size <= floor.threshold
    assert not effect.clears(floor)
    assert effect.negligible(floor)


def test_an_unrepeatable_effect_is_rejected_on_significance() -> None:
    floor = measure_noise_floor(BASE, "tvd")
    effect = measure_effect(BASE, [noul(0.81), noul(0.81), noul(0.80)], "tvd")
    assert effect.p_value > ALPHA
    assert effect.negligible(floor)


def test_permutation_p_cannot_beat_one_over_the_split_count() -> None:
    p, splits = permutation_p(BASE, [noul(0.0)] * 3, "tvd")
    assert splits == 56  # C(8, 3)
    assert p == pytest.approx(1.0 / 56)


def test_too_few_replicates_is_reported_as_underpowered() -> None:
    """With k this small no result could reach alpha, whatever it showed."""
    effect = measure_effect([noul(0.8), noul(0.8)], [noul(0.1)], "tvd")
    assert effect.underpowered()
    assert effect.p_value > ALPHA


def test_more_replicates_sharpen_rather_than_blur() -> None:
    """The estimator must converge: more data, smaller p, stable size."""
    small = measure_effect(BASE, [noul(0.60)] * 3, "tvd")
    large = measure_effect(BASE * 2, [noul(0.60)] * 8, "tvd")
    assert large.p_value <= small.p_value
    assert large.size == pytest.approx(small.size, abs=0.005)
    assert not large.underpowered()


def test_mean_distribution_averages_componentwise() -> None:
    mean = mean_distribution([noul(0.80), noul(0.90)])
    assert mean["yes"] == pytest.approx(0.85)


def test_classify_corroborates_when_both_modes_agree() -> None:
    floor = measure_noise_floor(BASE, "tvd")
    strong = measure_effect(BASE, [noul(0.60), noul(0.61), noul(0.60)], "tvd")
    assert classify({"delete": strong, "mask": strong}, floor) is Verdict.CORROBORATED


def test_classify_flags_mode_sensitivity_as_the_deletion_confound() -> None:
    floor = measure_noise_floor(BASE, "tvd")
    strong = measure_effect(BASE, [noul(0.60), noul(0.61), noul(0.60)], "tvd")
    flat = measure_effect(BASE, [noul(0.81), noul(0.81), noul(0.80)], "tvd")
    assert classify({"delete": strong, "mask": flat}, floor) is Verdict.MODE_SENSITIVE


def test_classify_flags_opposite_signs_as_mode_sensitive() -> None:
    floor = measure_noise_floor(BASE, "tvd")
    down = measure_effect(BASE, [noul(0.60), noul(0.61), noul(0.60)], "tvd")
    up = measure_effect(BASE, [noul(0.99), noul(0.98), noul(0.99)], "tvd")
    assert classify({"delete": down, "mask": up}, floor) is Verdict.MODE_SENSITIVE


def test_classify_calls_a_small_steady_effect_null() -> None:
    floor = measure_noise_floor(BASE, "tvd")
    flat = measure_effect(BASE, [noul(0.81), noul(0.81), noul(0.80)], "tvd")
    assert classify({"delete": flat, "mask": flat}, floor) is Verdict.NULL


def test_classify_will_not_call_an_underpowered_run_null() -> None:
    """Absence of evidence is not deadweight when there was no power to see it."""
    floor = measure_noise_floor(BASE, "tvd")
    weak = measure_effect([noul(0.8), noul(0.8)], [noul(0.80)], "tvd")
    assert classify({"delete": weak, "mask": weak}, floor) is Verdict.INDETERMINATE


def test_classify_reports_failure_rather_than_a_zero_effect() -> None:
    """A dropped request must never read as 'this segment does not matter'."""
    floor = measure_noise_floor(BASE, "tvd")
    good = measure_effect(BASE, [noul(0.81)] * 3, "tvd")
    broken = failed_effect("HTTP 429")
    assert classify({"delete": good, "mask": broken}, floor) is Verdict.FAILED
    assert not broken.ok
    assert rank_key({"delete": broken}) == -1.0


def test_classify_reports_the_resolution_limit_over_everything_else() -> None:
    floor = measure_noise_floor([one_hot()] * 5, "jsd")
    big = measure_effect([one_hot()] * 5, [noul(0.1)] * 3, "jsd")
    assert classify({"delete": big}, floor) is Verdict.AT_RESOLUTION_LIMIT


def test_rank_key_uses_the_weakest_mode() -> None:
    floor = measure_noise_floor(BASE, "tvd")
    strong = measure_effect(BASE, [noul(0.60)] * 3, "tvd")
    weak = measure_effect(BASE, [noul(0.78)] * 3, "tvd")
    assert rank_key({"delete": strong, "mask": weak}) == pytest.approx(weak.size)
    assert floor.value > 0
