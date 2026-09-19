"""Orchestration: baseline, controls, fan-out, assembly.

The order matters. The baseline and its noise floor are established first, and
if the baseline turns out to have no headroom the run stops there rather than
spending hundreds of requests measuring into a wall.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from vernier_scale.client import Call, JevClient, Outcome, run_calls
from vernier_scale.distance import normalised_entropy, primary_metric
from vernier_scale.noise import (
    Effect,
    NoiseFloor,
    Verdict,
    classify,
    failed_effect,
    measure_effect,
    measure_noise_floor,
    rank_key,
)
from vernier_scale.perturb import inject_placebos, render
from vernier_scale.segment import segment as split
from vernier_scale.types import (
    BaselineTag,
    Mode,
    Question,
    Reading,
    Segment,
    TrialTag,
)

QUESTION_ID = "verdict"

MIN_BASELINE_REPLICATES = 2
"""Below this there is no spread to measure, so there is no floor."""


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
                key=_widest,
            )
        )

    @property
    def unmeasured(self) -> tuple[Row, ...]:
        """Segments a failed call left unmeasured.

        These belong in the report body, not in a footnote. A segment nobody
        could measure is not a segment that does not matter, and leaving it out
        of every block would say exactly that by omission.
        """
        return tuple(r for r in self.content_rows if r.verdict is Verdict.FAILED)

    @property
    def indeterminate(self) -> tuple[Row, ...]:
        """Segments whose interval straddles the threshold — neither shown nor cleared."""
        return tuple(
            sorted(
                (r for r in self.content_rows if r.verdict is Verdict.INDETERMINATE),
                key=_widest,
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


def ablate(
    text: str,
    question: Question,
    client: JevClient,
    config: Config = Config(),  # noqa: B008 - Config is frozen, so sharing one is safe
    source: str = "<text>",
) -> Report:
    """Measure every segment's contribution to one question's answer.

    The baseline and its noise floor are established first. If the baseline
    turns out to have no headroom, the run stops there rather than spending
    hundreds of requests measuring into a wall.

    Args:
        text: The document to measure.
        question: The question to ask of it, unchanged across every call.
        client: Where to send the calls. Pass a stub to run without a network.
        config: Segmentation, perturbation modes and replicate counts.
        source: What to call the document in the report.
    """
    segments = prepare(text, config)
    questions = {QUESTION_ID: question}
    metric = primary_metric(question.type)

    baseline, base_errors, base_calls, usage = _measure_baseline(
        render(segments), questions, client, config
    )
    draft = _Draft(source, question, config, metric, tuple(segments), usage)
    if len(baseline) < MIN_BASELINE_REPLICATES:
        reason = base_errors[0] if base_errors else "no readings"
        return draft.abandoned(
            baseline=baseline,
            floor=_empty_floor(metric),
            calls=base_calls,
            errors=base_errors,
            aborted=f"baseline failed: {reason}",
            reason="the baseline could not be measured",
        )

    floor = measure_noise_floor(baseline, metric)
    if floor.at_resolution_limit:
        # Every baseline replicate put all its mass on one outcome. Ablation
        # could only ever flip the argmax or do nothing, which is the argmax
        # reading this tool exists to avoid. Say so; do not spend the fan-out.
        return draft.abandoned(
            baseline=baseline,
            floor=floor,
            calls=base_calls,
            errors=base_errors,
            aborted="baseline is at the resolution limit",
            reason="baseline distribution is saturated — no headroom to measure into",
        )

    grouped, trial_calls, trial_usage = _measure_trials(segments, questions, client, config)
    for unit, count in trial_usage.items():
        usage[unit] = usage.get(unit, 0) + count

    failures = list(base_errors)
    rows = [
        _row_for(
            seg,
            grouped=grouped,
            baseline=baseline,
            floor=floor,
            metric=metric,
            config=config,
            failures=failures,
        )
        for seg in segments
    ]
    return Report(
        source, question, config, metric, tuple(segments), tuple(baseline), floor,
        tuple(rows), _assess(rows, floor), base_calls + trial_calls,
        tuple(failures), usage,
    )


@dataclass(frozen=True, slots=True)
class _Draft:
    """The fields a report carries whether or not the measurement completed."""

    source: str
    question: Question
    config: Config
    metric: str
    segments: tuple[Segment, ...]
    usage: Mapping[str, int]

    def abandoned(
        self,
        *,
        baseline: Sequence[Reading],
        floor: NoiseFloor,
        calls: int,
        errors: Sequence[str],
        aborted: str,
        reason: str,
    ) -> Report:
        return Report(
            self.source, self.question, self.config, self.metric, self.segments,
            tuple(baseline), floor, (), Validity(False, (reason,)), calls,
            tuple(errors), self.usage, aborted=aborted,
        )


def _measure_baseline(
    state: str,
    questions: Mapping[str, Question],
    client: JevClient,
    config: Config,
) -> tuple[list[Reading], list[str], int, dict[str, int]]:
    """Call the unmodified document k times, each as its own request.

    Separate requests are the point. Asking the same question k times inside
    one request would measure structure within a call, which is not the
    quantity a noise floor is for.
    """
    calls = [
        Call(state, questions, BaselineTag(i)) for i in range(config.baseline_replicates)
    ]
    outcomes = run_calls(client, calls, config.concurrency)
    readings, errors = _readings(outcomes)
    return readings, errors, len(calls), _usage_of(outcomes)


def _measure_trials(
    segments: Sequence[Segment],
    questions: Mapping[str, Question],
    client: JevClient,
    config: Config,
) -> tuple[dict[tuple[int, Mode], list[Outcome]], int, dict[str, int]]:
    """One call per segment, per mode, per replicate, grouped by what it measures."""
    calls: list[Call] = []
    for seg in segments:
        for mode in config.modes:
            state = render(segments, omit=seg.index, mode=mode)
            calls.extend(
                Call(state, questions, TrialTag(seg.index, mode, rep))
                for rep in range(config.perturbed_replicates)
            )
    outcomes = run_calls(client, calls, config.concurrency)
    grouped: dict[tuple[int, Mode], list[Outcome]] = {}
    for outcome in outcomes:
        tag = outcome.tag
        if isinstance(tag, TrialTag):
            grouped.setdefault((tag.segment, tag.mode), []).append(outcome)
    return grouped, len(calls), _usage_of(outcomes)


def _row_for(
    seg: Segment,
    *,
    grouped: Mapping[tuple[int, Mode], list[Outcome]],
    baseline: Sequence[Reading],
    floor: NoiseFloor,
    metric: str,
    config: Config,
    failures: list[str],
) -> Row:
    """Turn one segment's trial outcomes into its measured row."""
    effects: dict[str, Effect] = {}
    for mode in config.modes:
        readings, errors = _readings(grouped.get((seg.index, mode), []))
        failures.extend(f"{seg.label} [{mode.value}]: {e}" for e in errors)
        effects[mode.value] = (
            measure_effect(baseline, readings, metric)
            if readings
            else failed_effect(errors[0] if errors else "no readings")
        )
    return Row(seg, effects, classify(effects, floor), rank_key(effects))


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
