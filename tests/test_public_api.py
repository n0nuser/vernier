"""The library surface: what an embedding caller is promised."""

from __future__ import annotations

import importlib
import importlib.metadata
import pkgutil
from pathlib import Path

import pytest

import vernier

RULEBOOK = Path(__file__).resolve().parents[1] / "examples" / "contributor-covenant-2.1.md"
SIGNAL = "A permanent ban from any sort of public interaction within the community."


def test_the_documented_example_runs() -> None:
    """The snippet in the package docstring, executed."""
    report = vernier.ablate(
        text=RULEBOOK.read_text(encoding="utf-8"),
        question=vernier.noul("Is a permanent ban proportionate for repeated harassment?"),
        client=vernier.StubJevClient(base=0.8, sensitive={SIGNAL: -0.35}),
        config=vernier.Config(concurrency=16),
    )
    assert report.validity.ok
    assert report.ranked[0].segment.label == "### 4. Permanent Ban"
    assert report.ranked[0].verdict is vernier.Verdict.CORROBORATED


def test_every_name_in_all_is_importable() -> None:
    missing = [name for name in vernier.__all__ if not hasattr(vernier, name)]
    assert missing == []


def test_all_is_sorted_and_free_of_duplicates() -> None:
    assert vernier.__all__ == sorted(set(vernier.__all__))


def test_no_private_name_is_exported() -> None:
    public = [n for n in vernier.__all__ if n != "__version__"]
    assert not [n for n in public if n.startswith("_")]


def test_version_matches_the_installed_package_metadata() -> None:
    """The distribution metadata is the single source of truth for the version."""
    assert vernier.__version__ == importlib.metadata.version("vernier")
    assert vernier.__version__[0].isdigit()


def test_an_unknown_attribute_raises() -> None:
    """Nothing widens the module namespace, so a consumer's typo is caught."""
    with pytest.raises(AttributeError):
        getattr(vernier, "definitely_not_exported")


def test_every_cli_error_is_catchable_as_a_vernier_error() -> None:
    from vernier.cli import UsageError

    assert issubclass(UsageError, vernier.VernierError)


def test_the_package_is_marked_typed() -> None:
    """PEP 561: without this marker a downstream type checker ignores us."""
    assert (Path(vernier.__file__).parent / "py.typed").is_file()


def test_importing_the_package_reads_nothing_and_calls_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No import-time side effects: no environment reads, no network, no output."""
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    for module in list(vars(vernier)):
        pass
    reloaded = importlib.reload(vernier)
    assert reloaded.__all__


def test_every_submodule_imports_cleanly() -> None:
    for info in pkgutil.iter_modules([str(Path(vernier.__file__).parent)]):
        importlib.import_module(f"vernier.{info.name}")


def test_a_missing_key_fails_at_construction_not_at_call_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(vernier.ConfigurationError):
        vernier.HttpJevClient.from_environment()


def test_the_http_client_takes_its_key_explicitly() -> None:
    """An embedding caller can hold several clients without touching the environment."""
    client = vernier.HttpJevClient(api_key="k", base_url="https://example.test")
    assert client.endpoint == "https://example.test/v1/systemone"
    assert client.call_count == 0


def test_every_error_descends_from_one_base() -> None:
    """One except clause catches everything vernier raises, and nothing else."""
    for error in (vernier.JevError, vernier.TilingError, vernier.QuestionError,
                  vernier.ConfigurationError):
        assert issubclass(error, vernier.VernierError)
    assert issubclass(vernier.VernierError, Exception)


@pytest.mark.parametrize(
    "build",
    [
        lambda: vernier.noul("is it?"),
        lambda: vernier.choice("which?", ["a", "b"]),
        lambda: vernier.score("how bad?", ["mild", "severe"]),
    ],
)
def test_question_constructors_produce_api_shaped_payloads(build: object) -> None:
    question = build()  # type: ignore[operator]
    payload = question.payload()
    assert payload["type"] in {"noul", "choice", "score"}
    assert payload["instructions"]


@pytest.mark.parametrize(
    ("build", "message"),
    [
        (lambda: vernier.noul(" "), "instructions"),
        (lambda: vernier.choice("q", ["only"]), "two distinct options"),
        (lambda: vernier.score("q", ["one"]), "two levels"),
    ],
)
def test_malformed_questions_are_rejected_with_a_reason(build: object, message: str) -> None:
    with pytest.raises(vernier.QuestionError, match=message):
        build()  # type: ignore[operator]


def test_metrics_are_usable_on_their_own() -> None:
    """The statistics are part of the surface, not buried in the pipeline."""
    assert vernier.tvd({"a": 0.5, "b": 0.5}, {"a": 0.5, "b": 0.5}) == 0.0
    assert vernier.jsd({"a": 1.0, "b": 0.0}, {"a": 0.0, "b": 1.0}) == 1.0
    assert vernier.normalised_entropy({"a": 0.5, "b": 0.5}) == 1.0
    assert vernier.resolution_limit(2, "tvd") > 0.0


def test_segmentation_is_usable_on_its_own() -> None:
    segments = vernier.segment("# A\n\nalpha\n\n## B\n\nbeta\n", "section")
    assert [s.label for s in segments] == ["# A", "## B"]
    assert "section" in vernier.SEGMENTERS


def test_rendering_is_a_separate_step_from_measuring() -> None:
    """Nothing prints during a run; the caller chooses if and how to render."""
    report = vernier.ablate(
        RULEBOOK.read_text(encoding="utf-8"),
        vernier.noul("is it?"),
        vernier.StubJevClient(base=0.8, sensitive={SIGNAL: -0.35}),
        vernier.Config(concurrency=16),
    )
    for render in (vernier.render_text, vernier.render_json, vernier.render_haze,
                   vernier.render_deadweight):
        assert render(report)
