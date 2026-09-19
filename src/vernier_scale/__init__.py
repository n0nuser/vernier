"""Measure meaning by perturbing text and watching a calibrated probability move.

vernier reads the probability distribution TypeSafe's Jev returns, rather than
the answer everyone keeps and the distribution everyone throws away. Remove one
segment of a document, ask the same question again, and measure how far the
distribution moved — against a noise floor established from repeated calls on
the unmodified text, so that a movement smaller than the model's own jitter is
never reported as a finding.

    import vernier_scale as vernier

    report = vernier.ablate(
        text=open("policy.md").read(),
        question=vernier.noul("Does this policy permit a refund here?"),
        client=vernier.HttpJevClient.from_environment(),
    )

    if not report.validity.ok:
        raise SystemExit(report.validity.reasons[0])

    for row in report.ranked:
        print(f"{row.strength:.4f}  {row.verdict.value:14}  {row.segment.label}")

Nothing is read from the environment, logged or printed unless you ask for it:
the client is passed in, and rendering is a separate step. Pass StubJevClient to
run the whole pipeline with no network and no key.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from vernier_scale.client import (
    Call,
    ConfigurationError,
    HttpJevClient,
    JevClient,
    JevError,
    Outcome,
    StubJevClient,
    run_calls,
)
from vernier_scale.distance import entropy, jsd, normalised_entropy, resolution_limit, tvd
from vernier_scale.errors import VernierError
from vernier_scale.noise import Effect, NoiseFloor, Verdict
from vernier_scale.questions import QuestionError, choice, from_mapping, noul, score
from vernier_scale.report import render_deadweight, render_haze, render_json, render_text
from vernier_scale.run import Config, Report, Row, Validity, ablate, baseline_haze
from vernier_scale.segment import SEGMENTERS, Segmenter, TilingError, segment
from vernier_scale.types import Mode, Question, Reading, Segment, SegmentKind

# Read eagerly, and deliberately. PEP 562 would defer this one filesystem
# lookup, but a module-level __getattr__ types every unknown attribute as
# valid, so a consumer's typo would check clean against a package that
# advertises py.typed. Keeping the namespace statically checkable is worth
# more than a millisecond, and reading our own installed metadata is not the
# kind of import-time side effect the rest of this package avoids.
try:
    __version__ = version("vernier-scale")
except PackageNotFoundError:  # a source tree that was never installed
    __version__ = "0.0.0.dev0"

__all__ = [
    "SEGMENTERS",
    "Call",
    "Config",
    "ConfigurationError",
    "Effect",
    "HttpJevClient",
    "JevClient",
    "JevError",
    "Mode",
    "NoiseFloor",
    "Outcome",
    "Question",
    "QuestionError",
    "Reading",
    "Report",
    "Row",
    "Segment",
    "SegmentKind",
    "Segmenter",
    "StubJevClient",
    "TilingError",
    "Validity",
    "Verdict",
    "VernierError",
    "__version__",
    "ablate",
    "baseline_haze",
    "choice",
    "entropy",
    "from_mapping",
    "jsd",
    "normalised_entropy",
    "noul",
    "render_deadweight",
    "render_haze",
    "render_json",
    "render_text",
    "resolution_limit",
    "run_calls",
    "score",
    "segment",
    "tvd",
]
