"""The command line: question assembly, exit codes, and offline operation."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from vernier_scale.cli import (
    EXIT_INVALID,
    EXIT_OK,
    EXIT_USAGE,
    UsageError,
    build_parser,
    build_question,
    main,
)

RULEBOOK = str(Path(__file__).resolve().parents[1] / "examples" / "contributor-covenant-2.1.md")
SIGNAL = "A permanent ban from any sort of public interaction"

OFFLINE = [
    "--stub",
    "--stub-base",
    "0.75",
    "--stub-sensitive",
    SIGNAL,
    "--baseline-calls",
    "5",
    "--trial-calls",
    "3",
    "--concurrency",
    "16",
]


def parse(argv: list[str]) -> object:
    args = build_parser().parse_args(argv)
    return build_question(args)


def test_a_noul_question_is_built_from_flags() -> None:
    q = parse(
        ["ablate", "doc.md", "--noul", "is it?", "--true", "yes means", "--false", "no means"]
    )
    assert q.type == "noul"  # type: ignore[attr-defined]
    assert q.payload()["criteria"] == {"true": "yes means", "false": "no means"}  # type: ignore[attr-defined]


def test_a_choice_question_needs_two_options() -> None:
    # The CLI presents every malformed question as a usage error, so that is
    # what a caller sees -- the blind `Exception` this replaced hid the wrapping.
    with pytest.raises(UsageError, match="two distinct options"):
        parse(["ablate", "doc.md", "--choice", "which?", "--option", "a"])
    q = parse(["ablate", "doc.md", "--choice", "which?", "--option", "a=first", "--option", "b"])
    assert q.payload()["criteria"] == {"a": "first", "b": None}  # type: ignore[attr-defined]


def test_a_score_question_takes_ordered_levels() -> None:
    q = parse(["ablate", "doc.md", "--score", "how bad?", "--level", "mild", "--level", "severe"])
    assert q.payload()["criteria"] == ["mild", "severe"]  # type: ignore[attr-defined]


def test_exactly_one_question_kind_is_required() -> None:
    with pytest.raises(Exception, match="exactly one"):
        parse(["ablate", "doc.md"])
    with pytest.raises(Exception, match="exactly one"):
        parse(
            ["ablate", "doc.md", "--noul", "a", "--choice", "b", "--option", "x", "--option", "y"]
        )


def test_a_question_file_is_accepted(tmp_path: Path) -> None:
    spec = tmp_path / "q.json"
    spec.write_text(json.dumps({"type": "noul", "instructions": "is it?"}))
    q = parse(["ablate", "doc.md", "--question-file", str(spec)])
    assert q.instructions == "is it?"  # type: ignore[attr-defined]


def test_a_malformed_question_file_is_a_usage_error(tmp_path: Path) -> None:
    spec = tmp_path / "q.json"
    spec.write_text("{not json")
    assert main(["ablate", RULEBOOK, "--question-file", str(spec), "--stub"]) == EXIT_USAGE


def test_ablate_runs_offline_and_succeeds(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["ablate", RULEBOOK, "--noul", "is a permanent ban right?", *OFFLINE])
    out = capsys.readouterr().out
    assert code == EXIT_OK
    assert "NOISE FLOOR" in out
    assert "### 4. Permanent Ban" in out


def test_json_output_parses(capsys: pytest.CaptureFixture[str]) -> None:
    main(["ablate", RULEBOOK, "--noul", "is it?", "--json", *OFFLINE])
    payload = json.loads(capsys.readouterr().out)
    assert payload["metric"] == "tvd"
    assert payload["noise_floor"]["threshold"] > 0


def test_deadweight_and_haze_run_offline(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["deadweight", RULEBOOK, "--noul", "is it?", *OFFLINE]) == EXIT_OK
    assert "DEADWEIGHT" in capsys.readouterr().out
    assert main(["haze", RULEBOOK, "--noul", "is it?", *OFFLINE]) == EXIT_OK
    assert "HAZE" in capsys.readouterr().out


def test_an_invalid_measurement_exits_nonzero(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        [
            "ablate",
            RULEBOOK,
            "--noul",
            "is it?",
            "--stub",
            "--stub-sensitive",
            "Recycling bins are collected",
            "--stub-shift",
            "-0.4",
            "--concurrency",
            "16",
        ]
    )
    assert code == EXIT_INVALID
    assert "MEASUREMENT INVALID" in capsys.readouterr().out


def test_a_missing_document_is_a_usage_error() -> None:
    assert main(["ablate", "/no/such/file.md", "--noul", "x", "--stub"]) == EXIT_USAGE


def test_too_few_baseline_calls_is_a_usage_error() -> None:
    argv = ["ablate", RULEBOOK, "--noul", "x", "--stub", "--baseline-calls", "1"]
    assert main(argv) == EXIT_USAGE


def test_stdin_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("# A\n\nalpha text here\n\n## B\n\nbeta text\n"))
    assert main(["ablate", "-", "--noul", "is it?", "--stub", "--concurrency", "8"]) == EXIT_OK


def test_an_empty_document_is_a_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("   \n"))
    assert main(["ablate", "-", "--noul", "x", "--stub"]) == EXIT_USAGE
