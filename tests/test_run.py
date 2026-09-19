"""End to end against the stub: controls, validity, and the abort paths."""

from __future__ import annotations

from pathlib import Path

import pytest

from vernier.client import Call, JevClient, Outcome, StubJevClient
from vernier.noise import Verdict
from vernier.report import render_deadweight, render_haze, render_json, render_text
from vernier.run import Config, ablate
from vernier.types import Mode, Question, SegmentKind

RULEBOOK = Path(__file__).resolve().parents[1] / "examples" / "contributor-covenant-2.1.md"
DOC = RULEBOOK.read_text(encoding="utf-8")
SIGNAL = "A permanent ban from any sort of public interaction within the community."
QUESTION = Question("noul", "Is a permanent ban proportionate?")
FAST = Config(concurrency=16, baseline_replicates=5, perturbed_replicates=3)


def instrument(**kw: object) -> StubJevClient:
    kw.setdefault("base", 0.75)
    kw.setdefault("sensitive", {SIGNAL: -0.35})
    return StubJevClient(**kw)  # type: ignore[arg-type]


def test_the_sensitive_segment_is_found_and_ranked_first() -> None:
    report = ablate(DOC, QUESTION, instrument(), FAST)
    assert report.validity.ok
    assert report.ranked
    assert report.ranked[0].segment.label == "### 4. Permanent Ban"
    assert report.ranked[0].verdict is Verdict.CORROBORATED


def test_removing_the_segment_moves_the_answer_in_the_right_direction() -> None:
    report = ablate(DOC, QUESTION, instrument(), FAST)
    top = report.ranked[0]
    assert all(e.direction < 0 for e in top.effects.values())


def test_the_control_segments_stay_inside_the_noise() -> None:
    """The measurement is only trustworthy if the placebos are inert."""
    report = ablate(DOC, QUESTION, instrument(), FAST)
    assert report.validity.control_rows
    for row in report.validity.control_rows:
        assert row.segment.kind is SegmentKind.PLACEBO
        assert row.verdict is not Verdict.CORROBORATED
        assert row.verdict is not Verdict.MODE_SENSITIVE


def test_a_control_that_moves_invalidates_the_whole_run() -> None:
    """If neutral boilerplate drives the number, no ranking may be printed."""
    client = instrument(sensitive={"Recycling bins are collected": -0.4})
    report = ablate(DOC, QUESTION, client, FAST)
    assert not report.validity.ok
    assert any("control segment" in r for r in report.validity.reasons)
    assert "MEASUREMENT INVALID" in render_text(report)
    assert "ATTRIBUTION" not in render_text(report)


def test_a_saturated_baseline_aborts_before_the_fan_out() -> None:
    """No headroom means no measurement — and no hundreds of wasted calls."""
    client = StubJevClient(base=1.0, jitter=0.0, question_type="choice")
    report = ablate(DOC, QUESTION, client, FAST)
    assert report.aborted
    assert report.floor.at_resolution_limit
    assert report.calls == FAST.baseline_replicates
    assert "RUN ABORTED" in render_text(report)


def test_a_dead_baseline_aborts_rather_than_guessing() -> None:
    report = ablate(DOC, QUESTION, StubJevClient(fail_on=("Covenant",)), FAST)
    assert report.aborted
    assert not report.validity.ok


def test_irrelevant_segments_land_in_the_deadweight() -> None:
    report = ablate(DOC, QUESTION, instrument(), FAST)
    labels = {r.segment.label for r in report.inside_noise}
    assert "## Attribution" in labels
    assert "### 4. Permanent Ban" not in labels


def test_a_failed_trial_never_becomes_a_zero_effect() -> None:
    """The worst bug this tool could have, asserted against.

    The trigger is the masked form of one heading, so exactly one
    (segment, mode) group fails and the rest of the run is untouched.
    """
    client = instrument(fail_on=("### 4. General Notes",))
    report = ablate(DOC, QUESTION, client, FAST)
    failed = [r for r in report.rows if r.verdict is Verdict.FAILED]
    assert [r.segment.label for r in failed] == ["### 4. Permanent Ban"]
    assert report.failures
    # A segment that could not be measured is neither a finding nor deadweight.
    assert all(r not in report.inside_noise for r in failed)
    assert all(r not in report.ranked for r in failed)
    assert report.unmeasured == tuple(failed)
    # Absent from every block would say "this segment does not matter" by
    # omission, which is the one thing the tool must never say about a
    # segment nobody could measure. It has to be named in the body.
    out = render_text(report)
    assert "UNMEASURED" in out
    assert "### 4. Permanent Ban" in out.split("UNMEASURED", 1)[1]


def _data_rows(report: object, text: str) -> list[str]:
    """The per-mode measurement lines of the ranking block, without its legend."""
    ranking = text.split("ATTRIBUTION", 1)[1].split("INSIDE THE NOISE", 1)[0]
    return [ln for ln in ranking.split("\n") if " p=" in ln]


def test_entropy_and_confidence_ride_alongside_each_row() -> None:
    """Spec: report entropy and Jev's own confidence next to the distance."""
    client = StubJevClient(question_type="choice", base=0.6, sensitive={SIGNAL: -0.3})
    report = ablate(DOC, Question("choice", "which?"), client, FAST)
    rows = _data_rows(report, render_text(report))
    assert rows
    assert all("H" in ln for ln in rows)
    assert all("conf" in ln for ln in rows)


def test_a_noul_run_reports_entropy_but_no_confidence() -> None:
    """A Noul carries no confidence, so none is invented for it."""
    report = ablate(DOC, QUESTION, instrument(), FAST)
    rows = _data_rows(report, render_text(report))
    assert rows
    assert all("H" in ln for ln in rows)
    assert not any("conf" in ln for ln in rows)


@pytest.mark.parametrize(("replicates", "caveated"), [(5, True), (8, False)])
def test_a_thin_baseline_says_its_floor_may_be_under_sampled(
    replicates: int, caveated: bool
) -> None:
    cfg = Config(baseline_replicates=replicates, perturbed_replicates=3, concurrency=16)
    out = render_text(ablate(DOC, QUESTION, instrument(), cfg))
    assert ("under-state the spread" in out) is caveated


def test_the_call_count_is_exactly_what_the_design_says() -> None:
    report = ablate(DOC, QUESTION, instrument(), FAST)
    segments = len(report.segments)
    expected = FAST.baseline_replicates + segments * len(FAST.modes) * FAST.perturbed_replicates
    assert report.calls == expected


def test_replicates_come_from_separate_requests() -> None:
    """Asking k times in one request would measure the wrong thing entirely."""
    seen: list[Call] = []

    class Recorder:
        def __init__(self) -> None:
            self.inner = instrument()

        def evaluate(self, call: Call) -> Outcome:
            seen.append(call)
            return self.inner.evaluate(call)

    client: JevClient = Recorder()
    ablate(DOC, QUESTION, client, Config(baseline_replicates=5, perturbed_replicates=3))
    assert all(len(c.questions) == 1 for c in seen)
    baseline_states = [c.state for c in seen[:5]]
    assert len(set(baseline_states)) == 1  # identical input, five separate calls


def test_running_without_controls_is_possible_but_uncontrolled() -> None:
    report = ablate(DOC, QUESTION, instrument(), Config(controls=0, concurrency=16))
    assert not report.validity.control_rows
    assert "uncontrolled" in render_text(report)


def test_both_modes_are_measured_for_every_segment() -> None:
    report = ablate(DOC, QUESTION, instrument(), FAST)
    for row in report.rows:
        assert set(row.effects) == {Mode.DELETE.value, Mode.MASK.value}


def test_a_single_mode_run_is_allowed() -> None:
    cfg = Config(modes=(Mode.MASK,), concurrency=16)
    report = ablate(DOC, QUESTION, instrument(), cfg)
    assert all(set(r.effects) == {"mask"} for r in report.rows)


def test_paragraph_segmentation_also_finds_the_signal() -> None:
    cfg = Config(segmentation="paragraph", concurrency=16)
    report = ablate(DOC, QUESTION, instrument(), cfg)
    assert report.validity.ok
    assert SIGNAL[:30] in report.ranked[0].segment.text


def test_a_choice_question_is_measured_with_jsd() -> None:
    client = StubJevClient(question_type="choice", base=0.6, sensitive={SIGNAL: -0.3})
    report = ablate(DOC, Question("choice", "which?"), client, FAST)
    assert report.metric == "jsd"
    assert report.baseline[0].confidence is not None


def test_json_output_carries_the_floor_and_every_segment() -> None:
    import json

    report = ablate(DOC, QUESTION, instrument(), FAST)
    payload = json.loads(render_json(report))
    assert payload["noise_floor"]["floor"] > 0
    assert payload["noise_floor"]["threshold"] > payload["noise_floor"]["floor"]
    assert len(payload["segments"]) == len(report.segments)
    assert payload["validity"]["ok"] is True
    top = next(s for s in payload["segments"] if s["rank"] == 1)
    assert top["label"] == "### 4. Permanent Ban"


def test_every_renderer_produces_output_for_the_same_run() -> None:
    report = ablate(DOC, QUESTION, instrument(), FAST)
    for text in (render_text(report), render_deadweight(report), render_haze(report)):
        assert "vernier" in text
        assert "NOISE FLOOR" in text


def test_deadweight_names_the_inert_sections() -> None:
    report = ablate(DOC, QUESTION, instrument(), FAST)
    out = render_deadweight(report)
    assert "DEADWEIGHT" in out
    assert "## Attribution" in out


@pytest.mark.parametrize(
    ("base", "expected"),
    [
        (0.50, "close to flat"),
        (0.80, "spread but leaning"),
        (0.97, "concentrated"),
    ],
)
def test_haze_reads_the_shape_of_the_baseline(base: float, expected: str) -> None:
    report = ablate(DOC, QUESTION, StubJevClient(base=base, jitter=0.01), FAST)
    out = render_haze(report)
    assert "HAZE" in out
    assert expected in out


@pytest.mark.parametrize("by", ["section", "paragraph", "line"])
def test_the_pipeline_runs_under_every_segmentation(by: str) -> None:
    cfg = Config(segmentation=by, baseline_replicates=3, perturbed_replicates=2, concurrency=16)
    report = ablate(DOC, QUESTION, instrument(), cfg)
    assert report.calls > 0
    assert render_text(report)
