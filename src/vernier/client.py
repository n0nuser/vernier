"""The System One client, and a stub that stands in for it.

The whole suite runs against :class:`StubJevClient`: no network, no key. The
protocol is narrow on purpose — one method, one request — because everything
interesting in vernier happens in how many times that method is called and with
what, not in the call itself.
"""

from __future__ import annotations

import json
import os
import random
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Mapping, Protocol, Sequence

from .types import Question, QuestionType, Reading

DEFAULT_BASE_URL = "https://api.typesafe.ai"
DEFAULT_MODEL = "jev-latest"
API_KEY_ENV = "TYPESAFE_API_KEY"
BASE_URL_ENV = "TYPESAFE_BASE_URL"

# 429 and 529 are the documented back-off cases; the 5xx family are transport
# hiccups equally safe to retry on an idempotent POST.
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504, 529})


class JevError(RuntimeError):
    """A call did not produce a usable answer."""


@dataclass(frozen=True, slots=True)
class Call:
    """One unit of work: a state to evaluate and the questions to ask of it."""

    state: str
    questions: Mapping[str, Question]
    tag: object = None


@dataclass(frozen=True, slots=True)
class Outcome:
    """The result of one call — an answer set, or the error that replaced it.

    A failure is a value, not an exception, because the one bug this tool must
    never have is a dropped request quietly becoming a zero delta, i.e. "this
    segment does not matter".
    """

    tag: object
    readings: Mapping[str, Reading] | None
    error: str | None = None
    usage: Mapping[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.readings is not None


def _as_float(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise JevError(f"{field} was {value!r}, expected a number")
    return float(value)


def reading_from_answer(answer: Mapping[str, object]) -> Reading:
    """Normalise any of the three answer shapes into a distribution."""
    kind = answer.get("type")
    if kind == "noul":
        # A Noul reports one number. Its distribution is the two-point
        # distribution that number defines, which is what makes the same
        # distance metric apply to all three question types.
        p = _as_float(answer.get("noul"), "noul")
        return Reading("noul", (("yes", p), ("no", 1.0 - p)), p, None)
    if kind in {"choice", "score"}:
        probs = answer.get("probabilities")
        if not isinstance(probs, Mapping) or not probs:
            raise JevError(f"{kind} answer carried no probabilities")
        items = tuple((str(k), _as_float(v, "probability")) for k, v in probs.items())
        confidence = answer.get("confidence")
        answered: str | float
        qtype: QuestionType
        if kind == "choice":
            chosen = answer.get("choice")
            if not isinstance(chosen, str):
                raise JevError("choice answer carried no chosen option")
            answered, qtype = chosen, "choice"
        else:
            answered, qtype = _as_float(answer.get("score"), "score"), "score"
        return Reading(
            qtype,
            tuple(sorted(items)),
            answered,
            _as_float(confidence, "confidence") if confidence is not None else None,
        )
    raise JevError(f"unrecognised answer type {kind!r}")


class JevClient(Protocol):
    """What the rest of vernier needs from an API."""

    def evaluate(self, call: Call) -> Outcome: ...


def run_calls(client: JevClient, calls: Sequence[Call], concurrency: int = 8) -> list[Outcome]:
    """Run calls in parallel, bounded, preserving order.

    Ablation varies the *state*, so each variant is necessarily its own request
    — there is nothing to batch. Concurrency is bounded because a run is
    hundreds of requests and an unbounded fan-out just converts them into 429s.
    """
    if not calls:
        return []
    workers = max(1, min(concurrency, len(calls)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(client.evaluate, calls))


@dataclass
class HttpJevClient:
    """Talks to POST /v1/systemone."""

    model: str = DEFAULT_MODEL
    api_key: str | None = None
    base_url: str | None = None
    timeout: float = 60.0
    retries: int = 4

    def __post_init__(self) -> None:
        self._key = self.api_key or os.environ.get(API_KEY_ENV)
        self._url = (
            (self.base_url or os.environ.get(BASE_URL_ENV) or DEFAULT_BASE_URL).rstrip("/")
            + "/v1/systemone"
        )
        self._calls = 0
        self._lock = threading.Lock()

    @property
    def call_count(self) -> int:
        with self._lock:
            return self._calls

    def evaluate(self, call: Call) -> Outcome:
        if not self._key:
            return Outcome(call.tag, None, f"{API_KEY_ENV} is not set")
        payload = {
            "state": call.state,
            "model": self.model,
            "questions": {k: q.payload() for k, q in call.questions.items()},
        }
        try:
            body = self._post(json.dumps(payload).encode())
        except JevError as exc:
            return Outcome(call.tag, None, str(exc))
        try:
            answers = body["answers"]
            if not isinstance(answers, Mapping):
                raise JevError("answers was not a map")
            readings = {
                str(k): reading_from_answer(v)
                for k, v in answers.items()
                if isinstance(v, Mapping)
            }
        except (KeyError, TypeError, ValueError, JevError) as exc:
            return Outcome(call.tag, None, f"malformed response: {exc}")
        raw_usage = body.get("usage")
        usage = raw_usage if isinstance(raw_usage, Mapping) else {}
        return Outcome(
            call.tag,
            readings,
            None,
            {str(k): int(v) for k, v in usage.items() if isinstance(v, (int, float))},
        )

    def _post(self, body: bytes) -> dict[str, object]:
        for attempt in range(self.retries + 1):
            req = urllib.request.Request(
                self._url,
                data=body,
                headers={
                    "Authorization": f"Bearer {self._key}",
                    "Content-Type": "application/json",
                    "User-Agent": "vernier/0.1",
                },
                method="POST",
            )
            try:
                with self._lock:
                    self._calls += 1
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    parsed = json.load(resp)
                if not isinstance(parsed, dict):
                    raise JevError("response was not a JSON object")
                return parsed
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode(errors="replace").strip()
                if exc.code in RETRY_STATUSES and attempt < self.retries:
                    _backoff(exc.headers.get("Retry-After"), attempt)
                    continue
                raise JevError(f"HTTP {exc.code}: {detail[:200] or exc.reason}") from exc
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                if attempt < self.retries:
                    _backoff(None, attempt)
                    continue
                raise JevError(f"request failed: {exc}") from exc
        raise JevError("retries exhausted")


def _backoff(retry_after: str | None, attempt: int) -> None:
    if retry_after:
        try:
            time.sleep(min(float(retry_after), 60.0))
            return
        except ValueError:
            pass
    time.sleep(min(2.0**attempt, 30.0) * (0.5 + random.random() / 2))


@dataclass
class StubJevClient:
    """A deterministic stand-in with the same observable quirks as the API.

    Three of those quirks are what the statistics have to survive, so the stub
    reproduces all three:

    * answers are rounded to two decimals, so the grid is real;
    * identical calls differ slightly, so the noise floor has something to
      measure;
    * a distribution can saturate at 1.0, so the resolution-limit path is
      reachable from a test.

    ``sensitive`` maps a substring to how much removing it shifts the answer,
    which lets a test assert that the segment carrying it clears the floor and
    that the neutral placebos do not.
    """

    base: float = 0.5
    sensitive: Mapping[str, float] = field(default_factory=dict)
    jitter: float = 0.01
    seed: int = 0
    question_type: QuestionType = "noul"
    options: Sequence[str] = ("yes", "no", "unclear")
    fail_on: Sequence[str] = ()

    def __post_init__(self) -> None:
        self._calls = 0
        self._lock = threading.Lock()

    @property
    def call_count(self) -> int:
        with self._lock:
            return self._calls

    def evaluate(self, call: Call) -> Outcome:
        with self._lock:
            self._calls += 1
            nth = self._calls
        for needle in self.fail_on:
            if needle in call.state:
                return Outcome(call.tag, None, "stub: injected failure")
        value = self.base + sum(w for s, w in self.sensitive.items() if s in call.state)
        # Jitter keyed on the call index, not the state: run-to-run noise is a
        # property of the call, which is exactly what a noise floor measures.
        rng = random.Random(f"{self.seed}:{nth}")
        value += rng.uniform(-self.jitter, self.jitter)
        value = min(max(value, 0.0), 1.0)
        readings = {k: self._reading(value) for k in call.questions}
        return Outcome(call.tag, readings, None, {"input_tokens": len(call.state) // 4})

    def _reading(self, value: float) -> Reading:
        if self.question_type == "noul":
            p = round(value, 2)
            return Reading("noul", (("yes", p), ("no", round(1.0 - p, 2))), p, None)
        n = len(self.options)
        head = round(value, 2)
        rest = round((1.0 - head) / (n - 1), 2) if n > 1 else 0.0
        probs = [(self.options[0], head)] + [(o, rest) for o in self.options[1:]]
        confidence = round(head, 2)
        if self.question_type == "choice":
            return Reading("choice", tuple(sorted(probs)), self.options[0], confidence)
        expected = sum(i * p for i, (_, p) in enumerate(probs))
        return Reading(
            "score",
            tuple(sorted((str(i), p) for i, (_, p) in enumerate(probs))),
            round(expected, 2),
            confidence,
        )
