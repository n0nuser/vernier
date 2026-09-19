"""The client boundary: answer shapes in, readings out, failures as values."""

from __future__ import annotations

import pytest

from vernier.client import (
    Call,
    JevError,
    Outcome,
    StubJevClient,
    reading_from_answer,
    run_calls,
)
from vernier.types import BaselineTag, Question

Q = {"verdict": Question("noul", "does it?")}


def _p(client: StubJevClient, state: str) -> float:
    """The yes-probability the stub reports for a state."""
    readings = client.evaluate(Call(state, Q)).readings
    assert readings is not None
    return readings["verdict"].distribution["yes"]


def test_a_noul_answer_becomes_a_two_point_distribution() -> None:
    r = reading_from_answer({"type": "noul", "noul": 0.92})
    assert r.distribution == {"yes": 0.92, "no": pytest.approx(0.08)}
    assert r.confidence is None  # a Noul carries none, per the API


def test_a_choice_answer_keeps_its_full_distribution() -> None:
    r = reading_from_answer(
        {
            "type": "choice",
            "choice": "technical",
            "probabilities": {"billing": 0.08, "technical": 0.85, "sales": 0.07},
            "confidence": 0.82,
        }
    )
    assert r.answer == "technical"
    assert r.distribution["technical"] == 0.85
    assert r.confidence == 0.82


def test_a_score_answer_is_read_over_its_levels() -> None:
    r = reading_from_answer(
        {
            "type": "score",
            "score": 1.6,
            "legend": {"0": "Calm", "1": "Frustrated", "2": "Very angry"},
            "probabilities": {"0": 0.05, "1": 0.3, "2": 0.65},
            "confidence": 0.78,
        }
    )
    assert r.answer == 1.6
    assert r.support == ("0", "1", "2")


def test_a_one_hot_reading_is_recognised() -> None:
    r = reading_from_answer(
        {"type": "choice", "choice": "a", "probabilities": {"a": 1.0, "b": 0.0}, "confidence": 1.0}
    )
    assert r.is_one_hot


def test_an_unknown_answer_type_is_an_error() -> None:
    with pytest.raises(JevError):
        reading_from_answer({"type": "vibes", "vibes": 1})


def test_a_choice_without_probabilities_is_an_error() -> None:
    with pytest.raises(JevError):
        reading_from_answer({"type": "choice", "choice": "a", "probabilities": {}})


def test_the_stub_needs_no_network_or_key() -> None:
    out = StubJevClient().evaluate(Call("some document", Q))
    assert out.ok
    assert out.readings is not None


def test_the_stub_rounds_to_the_same_grid_as_the_api() -> None:
    value = _p(StubJevClient(base=0.617), "doc")
    assert value == round(value, 2)


def test_identical_calls_to_the_stub_still_differ_a_little() -> None:
    """Without jitter there would be no noise floor to measure."""
    client = StubJevClient(base=0.5, jitter=0.02)
    assert len({_p(client, "doc") for _ in range(12)}) > 1


def test_the_stub_shifts_on_its_declared_sensitive_substring() -> None:
    client = StubJevClient(base=0.8, sensitive={"SECRET": -0.4}, jitter=0.0)
    with_it = _p(client, "a SECRET b")
    without = _p(client, "a b")
    assert without - with_it == pytest.approx(0.4, abs=0.02)


def test_a_failure_is_a_value_not_an_exception() -> None:
    client = StubJevClient(fail_on=("poison",))
    out = client.evaluate(Call("a poison b", Q))
    assert not out.ok
    assert out.readings is None
    assert out.error


def test_run_calls_preserves_order_and_counts_every_call() -> None:
    client = StubJevClient()
    calls = [Call(f"doc {i}", Q, BaselineTag(i)) for i in range(20)]
    outs = run_calls(client, calls, concurrency=6)
    assert [o.tag for o in outs] == [BaselineTag(i) for i in range(20)]
    assert client.call_count == 20


def test_run_calls_on_an_empty_list_does_nothing() -> None:
    assert run_calls(StubJevClient(), []) == []


def test_outcome_without_readings_is_not_ok() -> None:
    assert not Outcome(None, None, "boom").ok
