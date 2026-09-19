"""Orchestration: baseline, controls, fan-out, assembly.

The order matters. The baseline and its noise floor are established first, and
if the baseline turns out to have no headroom the run stops there rather than
spending hundreds of requests measuring into a wall.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence, cast

from .client import Call, JevClient, Outcome, run_calls
from .distance import normalised_entropy, primary_metric
from .noise import (
    Effect,
    NoiseFloor,
    Verdict,
    classify,
    failed_effect,
    measure_effect,
    measure_noise_floor,
    rank_key,
)
from .perturb import inject_placebos, render
from .segment import segment as split
from .types import Mode, Question, Reading, Segment, SegmentKind

QUESTION_ID = "verdict"


@dataclass(frozen=True, slots=True)
class Config:
    segmentation: str = "section"
    modes: tuple[Mode, ...] = (Mode.DELETE, Mode.MASK)
    baseline_replicates: int = 5
    perturbed_replicates: int = 3
    concurrency: int = 8
    controls: int = 2


@dataclass(frozen=True, slots=True)
class Row:
    """One segment's measurement under every mode."""

    segment: Segment
    effects: dict[str, Effect]
    verdict: Verdict
    strength: float

    @property
    def is_control(self) -> bool:
        return self.segment.is_control


@dataclass(frozen=True, slots=True)
class Validity:
    """Whether the run is allowed to print a ranking at all."""

    ok: bool
    reasons: tuple[str, ...] = ()
    control_rows: tuple[Row, ...] = ()


@dataclass(frozen=True, slots=True)
class Report:
    source: str
    question: Question
    config: Config
    metric: str
    segments: tuple[Segment, ...]
    baseline: tuple[Reading, ...]
    floor: NoiseFloor
    rows: tuple[Row, ...]
    validity: Validity
    calls: int
    failures: tuple[str, ...] = ()
    usage: Mapping[str, int] = field(default_factory=dict)
    aborted: str | None = None

    @property
    def content_rows(self) -> tuple[Row, ...]:
        return tuple(r for r in self.rows if not r.is_control)

    @property
    def ranked(self) -> tuple[Row, ...]:
        """Segments that cleared the floor, strongest first.

        A segment whose effect is inside the noise is never ranked — it has no
        measured position to hold.
        """
        keep = [
            r
            for r in self.content_rows
            if r.verdict in {Verdict.CORROBORATED, Verdict.MODE_SENSITIVE}
        ]
        return tuple(sorted(keep, key=lambda r: r.strength, reverse=True))

    @property
    def inside_noise(self) -> tuple[Row, ...]:
        """The deadweight: segments whose effect is below the floor, with power to say so."""
        return tuple(
            sorted(
                (r for r in self.content_rows if r.verdict is Verdict.NULL),
                key=lambda r: _widest(r),
            )
        )

    @property
    def indeterminate(self) -> tuple[Row, ...]:
        """Segments whose interval straddles the threshold — neither shown nor cleared."""
        return tuple(
            sorted(
                (r for r in self.content_rows if r.verdict is Verdict.INDETERMINATE),
                key=lambda r: _widest(r),
                reverse=True,
            )
        )


def prepare(text: str, config: Config) -> list[Segment]:
    """Segment the document and inject the control condition."""
    segments = split(text, config.segmentation)
    if config.controls > 0:
        segments = inject_placebos(segments, config.controls)
    return segments


def _usage_of(outcomes: Sequence[Outcome]) -> dict[str, int]:
    total: dict[str, int] = {}
    for o in outcomes:
        for k, v in o.usage.items():
            total[k] = total.get(k, 0) + v
    return total


def _readings(outcomes: Sequence[Outcome]) -> tuple[list[Reading], list[str]]:
    good: list[Reading] = []
    errors: list[str] = []
    for o in outcomes:
        if o.ok and o.readings is not None and QUESTION_ID in o.readings:
            good.append(o.readings[QUESTION_ID])
        else:
            errors.append(o.error or "answer missing from response")
    return good, errors


def run_ablate(
    text: str,
    question: Question,
    client: JevClient,
    config: Config = Config(),
    source: str = "<text>",
) -> Report:
    """Measure every segment's contribution to one question's answer."""
    segments = prepare(text, config)
    questions = {QUESTION_ID: question}
    metric = primary_metric(question.type)
    baseline_state = render(segments)

    # --- baseline and noise floor, before anything else is spent ------------
    base_calls = [
        Call(baseline_state, questions, ("baseline", i)) for i in range(config.baseline_replicates)
    ]
    base_out = run_calls(client, base_calls, config.concurrency)
    baseline, base_errors = _readings(base_out)
    usage = _usage_of(base_out)
    if len(baseline) < 2:
        return Report(
            source, question, config, metric, tuple(segments), tuple(baseline),
            _empty_floor(metric), (), Validity(False, ("the baseline could not be measured",)),
            len(base_calls), tuple(base_errors), usage,
            aborted="baseline failed: " + (base_errors[0] if base_errors else "no readings"),
        )
    floor = measure_noise_floor(baseline, metric)

    if floor.at_resolution_limit:
        # Every baseline replicate put all its mass on one outcome. Ablation
        # could only ever flip the argmax or do nothing, which is the argmax
        # delta this tool exists to avoid. Say so; do not spend the fan-out.
        return Report(
            source, question, config, metric, tuple(segments), tuple(baseline), floor, (),
            Validity(False, ("baseline distribution is saturated — no headroom to measure into",)),
            len(base_calls), tuple(base_errors), usage,
            aborted="baseline is at the resolution limit",
        )

    # --- one call per (segment, mode, replicate) ----------------------------
    trials: list[Call] = []
    for seg in segments:
        for mode in config.modes:
            state = render(segments, omit=seg.index, mode=mode)
            for rep in range(config.perturbed_replicates):
                trials.append(Call(state, questions, (seg.index, mode.value, rep)))
    trial_out = run_calls(client, trials, config.concurrency)
    for k, v in _usage_of(trial_out).items():
        usage[k] = usage.get(k, 0) + v

    grouped: dict[tuple[int, str], list[Outcome]] = {}
    for outcome in trial_out:
        tag = cast(tuple[int, str, int], outcome.tag)
        grouped.setdefault((tag[0], tag[1]), []).append(outcome)

    failures = list(base_errors)
    rows: list[Row] = []
    for seg in segments:
        effects: dict[str, Effect] = {}
        for mode in config.modes:
            outcomes = grouped.get((seg.index, mode.value), [])
            readings, errors = _readings(outcomes)
            failures.extend(f"{seg.label} [{mode.value}]: {e}" for e in errors)
            effects[mode.value] = (
                measure_effect(baseline, readings, metric)
                if readings
                else failed_effect(errors[0] if errors else "no readings")
            )
        rows.append(Row(seg, effects, classify(effects, floor), rank_key(effects)))

    validity = _assess(rows, floor)
    return Report(
        source, question, config, metric, tuple(segments), tuple(baseline), floor,
        tuple(rows), validity, len(base_calls) + len(trials), tuple(failures), usage,
    )


def _widest(row: Row) -> float:
    """The largest effect size any mode measured for this segment."""
    return max((e.size for e in row.effects.values() if e.ok), default=0.0)


def _empty_floor(metric: str) -> NoiseFloor:
    return NoiseFloor(metric, (), (), 0.0, 0.0, 0.0, False, 0.0)


def _assess(rows: Sequence[Row], floor: NoiseFloor) -> Validity:
    """Decide whether the controls permit a ranking to be printed.

    A placebo section is unrelated office boilerplate. Removing it cannot
    change what a rulebook says. If the number moves anyway, the instrument is
    responding to something other than meaning — and a ranking built on it
    would be a confident answer from a broken gauge.
    """
    controls = tuple(r for r in rows if r.is_control)
    reasons: list[str] = []
    for row in controls:
        if row.verdict is Verdict.FAILED:
            reasons.append(f"control segment {row.segment.label!r} could not be measured")
        elif row.verdict in {Verdict.CORROBORATED, Verdict.MODE_SENSITIVE}:
            worst = max(e.size for e in row.effects.values() if e.ok)
            reasons.append(
                f"control segment {row.segment.label!r} moved the distribution by "
                f"{worst:.4f}, above the {floor.threshold:.4f} significance threshold"
            )
    broken = [r for r in rows if not r.is_control and r.verdict is Verdict.FAILED]
    if broken and len(broken) > len(rows) / 4:
        reasons.append(f"{len(broken)} of {len(rows)} segments failed to measure")
    return Validity(not reasons, tuple(reasons), controls)


def baseline_haze(report: Report) -> float:
    """How undecided the unmodified document leaves the question, in [0, 1]."""
    if not report.baseline:
        return 0.0
    return sum(normalised_entropy(r.distribution) for r in report.baseline) / len(report.baseline)


def agreed_entropy_shift(row: Row) -> float | None:
    """The entropy change both perturbation modes support, or None.

    The conservative reading: the smaller of the two magnitudes, and only when
    the modes agree on direction. Deleting text shortens the document, which
    tends to sharpen any reading on its own; requiring the mask to agree keeps
    that artefact from being reported as a source of ambiguity.
    """
    values = [e.entropy_delta for e in row.effects.values() if e.ok]
    if not values:
        return None
    if len({v >= 0 for v in values}) > 1:
        return None
    return min(values, key=abs)
