"""The noise floor, and what counts as a finding against it.

The asymmetry here is deliberate and is the whole argument of the tool:

* the **floor** is the *largest* distance seen between two identical calls —
  the worst the instrument does when nothing changed;
* an **effect** is the *smallest* distance seen between the baseline and a
  perturbed variant — the least that segment's removal can have done.

A segment is reported only when its smallest effect exceeds the largest noise.
Both quantities are measured with the same metric on the same scale, so the
comparison means something.
"""

from __future__ import annotations

import itertools
import statistics
from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Sequence

from .distance import cross, distance, normalised_entropy, pairwise, resolution_limit
from .types import Reading

ALPHA = 0.05
"""Significance level for the permutation test."""

MAX_PERMUTATIONS = 20_000
"""Above this many splits, the exact test is sampled rather than enumerated."""


class Verdict(str, Enum):
    """What the instrument can say about one measurement."""

    CORROBORATED = "corroborated"
    """Above the floor under both perturbation modes. A finding."""

    MODE_SENSITIVE = "mode-sensitive"
    """Above the floor under one mode only — the deletion confound, visible."""

    INDETERMINATE = "indeterminate"
    """The effect interval straddles the threshold. More replicates would settle it."""

    NULL = "null"
    """Wholly inside the noise floor. Not a finding, in either direction."""

    AT_RESOLUTION_LIMIT = "at-resolution-limit"
    """The baseline left no headroom to measure into. Not a result."""

    FAILED = "failed"
    """A call did not come back. Never silently a zero."""


@dataclass(frozen=True, slots=True)
class NoiseFloor:
    """What the instrument does when the input does not change."""

    metric: str
    replicates: tuple[Reading, ...]
    spreads: tuple[float, ...]
    observed: float
    quantization: float
    value: float
    saturated: bool

    @property
    def at_resolution_limit(self) -> bool:
        """The measured spread vanished under a saturated baseline.

        Five identical one-hot readings say the jitter is below the grid, not
        that there is none. Ranking off that would be reporting the rounding.
        """
        return self.saturated and self.observed == 0.0

    @property
    def limited_by(self) -> str:
        return "quantization" if self.quantization >= self.observed else "run-to-run spread"

    @property
    def threshold(self) -> float:
        """The floor plus one resolution step: what an effect must beat.

        The floor itself is the largest of only ``k(k-1)/2`` observed pairs, so
        it is a sample range and sample ranges run small — the true worst case
        is likely a little wider than the one five calls happened to show. One
        extra grid step is the smallest margin that cannot be manufactured by
        that under-estimate, and it keeps a finding from resting on a
        difference the instrument can only just express.
        """
        return self.value + self.quantization


def measure_noise_floor(replicates: Sequence[Reading], metric: str) -> NoiseFloor:
    """Establish the floor from k identical calls on the unmodified document.

    The replicates must come from k *separate* requests. Asking the same
    question k times inside one request measures within-call structure, which
    is not the quantity a floor is for.
    """
    if len(replicates) < 2:
        raise ValueError("a noise floor needs at least two baseline replicates")
    spreads = pairwise(replicates, metric)
    observed = max(spreads) if spreads else 0.0
    support = max(len(r.support) for r in replicates)
    quantization = resolution_limit(support, metric)
    return NoiseFloor(
        metric=metric,
        replicates=tuple(replicates),
        spreads=tuple(spreads),
        observed=observed,
        quantization=quantization,
        # Never zero: the grid alone can manufacture a difference this large.
        value=max(observed, quantization),
        saturated=any(r.is_one_hot for r in replicates),
    )


def mean_distribution(readings: Sequence[Reading]) -> dict[str, float]:
    """The componentwise mean of a set of readings.

    Averaging is what makes more replicates help: the mean of k calls carries
    roughly ``1/sqrt(k)`` of a single call's jitter.
    """
    keys: set[str] = set()
    for r in readings:
        keys |= set(r.distribution)
    n = len(readings)
    return {k: sum(r.distribution.get(k, 0.0) for r in readings) / n for k in sorted(keys)}


def permutation_p(
    baseline: Sequence[Reading], perturbed: Sequence[Reading], metric: str
) -> tuple[float, int]:
    """Exact two-sample permutation test on the mean-to-mean distance.

    The null hypothesis is that the two groups of readings are interchangeable
    — that perturbing the document changed nothing, and the difference between
    the groups is the same run-to-run jitter the noise floor measures.

    Pool the readings, and over every way of splitting the pool back into
    groups of the same sizes, count how often the split separates the means at
    least as far as the real one did. That fraction is the p-value. It assumes
    nothing about the shape of the noise, which matters here because the
    readings are quantized to a coarse grid and are nothing like Gaussian.

    Ties count against significance, which is the conservative direction and a
    common outcome on a 2dp grid.

    Returns the p-value and the number of splits considered. The smallest
    p-value attainable is ``1 / splits``, so a run with too few replicates
    cannot manufacture significance.
    """
    pool = list(baseline) + list(perturbed)
    n, k = len(pool), len(perturbed)
    if n < 2 or k == 0 or k == n:
        return 1.0, 1
    observed = distance_of_means(baseline, perturbed, metric)
    indices = range(n)
    total = 0
    at_least = 0
    for combo in itertools.combinations(indices, k):
        pick = set(combo)
        group_b = [pool[i] for i in pick]
        group_a = [pool[i] for i in indices if i not in pick]
        stat = distance_of_means(group_a, group_b, metric)
        total += 1
        # A tolerance one thousandth of a grid step keeps float noise from
        # making an identical split look smaller than the observed one.
        if stat >= observed - 1e-12:
            at_least += 1
        if total >= MAX_PERMUTATIONS:
            break
    return at_least / total, total


def distance_of_means(
    a: Sequence[Reading], b: Sequence[Reading], metric: str
) -> float:
    """Distance between the mean distributions of two groups of readings."""
    return _metric(mean_distribution(a), mean_distribution(b), metric)


def _metric(p: Mapping[str, float], q: Mapping[str, float], metric: str) -> float:
    from .distance import jsd, tvd

    return tvd(p, q) if metric == "tvd" else jsd(p, q)


@dataclass(frozen=True, slots=True)
class Effect:
    """How far one perturbation moved the distribution.

    Two independent hurdles, because they answer different questions:

    * ``size`` against the noise floor asks whether the movement is large
      enough to matter — practical significance;
    * ``p_value`` asks whether a movement that size could have come from the
      run-to-run jitter alone — statistical significance.

    A finding has to clear both. A big move measured once proves nothing, and a
    perfectly repeatable move of half a grid step is not worth reporting.
    """

    size: float
    p_value: float
    permutations: int
    distances: tuple[float, ...]
    low: float
    high: float
    entropy_delta: float
    confidence_delta: float | None
    direction: float
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    def clears(self, floor: NoiseFloor, alpha: float = ALPHA) -> bool:
        """Above the noise floor, and not explainable as jitter."""
        return self.ok and self.size > floor.threshold and self.p_value <= alpha

    def negligible(self, floor: NoiseFloor) -> bool:
        """The effect, whatever its sign, is smaller than the floor.

        This is an equivalence claim rather than a failure to reject, and it is
        what ``deadweight`` needs. It is only meaningful when the run had the
        power to have seen an effect — see :meth:`underpowered` — which is why
        :func:`classify` checks both.

        Note what it does *not* say: a segment can be negligible here and still
        have a p-value below alpha. That combination means the movement is
        real, perfectly repeatable, and too small to matter.
        """
        return self.ok and self.size <= floor.threshold

    def underpowered(self, alpha: float = ALPHA) -> bool:
        """True when this run could not have reached significance at all.

        With ``k`` replicates the smallest attainable p-value is ``1/splits``.
        If that floor is above alpha, a null result says nothing about the
        segment and everything about the number of calls.
        """
        return self.permutations > 0 and 1.0 / self.permutations > alpha


def measure_effect(
    baseline: Sequence[Reading], perturbed: Sequence[Reading], metric: str
) -> Effect:
    """Compare a baseline group against a perturbed group.

    The perturbed condition is replicated too. A shortened document can sit
    nearer a decision boundary where the model is noisier, so a single
    perturbed call carries uncertainty comparable to the floor itself.
    """
    if not baseline or not perturbed:
        return Effect(0.0, 1.0, 0, (), 0.0, 0.0, 0.0, None, 0.0, "no readings")
    distances = cross(baseline, perturbed, metric)
    size = distance_of_means(baseline, perturbed, metric)
    p_value, permutations = permutation_p(baseline, perturbed, metric)
    base_ent = statistics.fmean(normalised_entropy(r.distribution) for r in baseline)
    pert_ent = statistics.fmean(normalised_entropy(r.distribution) for r in perturbed)
    base_conf = [r.confidence for r in baseline if r.confidence is not None]
    pert_conf = [r.confidence for r in perturbed if r.confidence is not None]
    confidence_delta = (
        statistics.fmean(pert_conf) - statistics.fmean(base_conf)
        if base_conf and pert_conf
        else None
    )
    return Effect(
        size=size,
        p_value=p_value,
        permutations=permutations,
        distances=tuple(distances),
        low=min(distances),
        high=max(distances),
        entropy_delta=pert_ent - base_ent,
        confidence_delta=confidence_delta,
        direction=_direction(baseline, perturbed),
    )


def failed_effect(error: str) -> Effect:
    return Effect(0.0, 1.0, 0, (), 0.0, 0.0, 0.0, None, 0.0, error)


def _direction(baseline: Sequence[Reading], perturbed: Sequence[Reading]) -> float:
    """Signed shift in the mass on the baseline's leading outcome.

    Negative means removing the segment took mass away from what the document
    otherwise concluded: the segment was holding the verdict up.
    """
    lead = max(baseline[0].distribution.items(), key=lambda kv: kv[1])[0]
    before = statistics.fmean(r.distribution.get(lead, 0.0) for r in baseline)
    after = statistics.fmean(r.distribution.get(lead, 0.0) for r in perturbed)
    return after - before


def classify(by_mode: dict[str, Effect], floor: NoiseFloor) -> Verdict:
    """Combine the per-mode effects into one verdict.

    Requiring both modes to agree is right as a *label* and wrong as a gate: a
    segment that moves the number when deleted but not when masked is telling
    you the movement came from the document's shape, not its meaning. That is a
    finding about the measurement, so it is reported rather than discarded.
    """
    if not by_mode:
        return Verdict.FAILED
    if any(not e.ok for e in by_mode.values()):
        return Verdict.FAILED
    if floor.at_resolution_limit:
        return Verdict.AT_RESOLUTION_LIMIT
    clearing = [m for m, e in by_mode.items() if e.clears(floor)]
    if clearing:
        if len(clearing) == len(by_mode) and len(by_mode) > 1:
            signs = {e.direction >= 0 for e in by_mode.values()}
            return Verdict.CORROBORATED if len(signs) == 1 else Verdict.MODE_SENSITIVE
        return Verdict.MODE_SENSITIVE
    # Nothing cleared. "Did not clear" is not the same claim as "moved nothing",
    # and the difference is whether the run could have seen an effect at all.
    if any(e.underpowered() for e in by_mode.values()):
        return Verdict.INDETERMINATE
    if all(e.negligible(floor) for e in by_mode.values()):
        return Verdict.NULL
    # Movement larger than the floor that the permutation test could not
    # separate from jitter: real enough to see, too unsteady to assert.
    return Verdict.INDETERMINATE


def rank_key(by_mode: dict[str, Effect]) -> float:
    """Rank on the weakest mode: the effect size both perturbations support.

    Taking the max would let the deletion confound choose the winner.
    """
    usable = [e.size for e in by_mode.values() if e.ok]
    return min(usable) if usable else -1.0
