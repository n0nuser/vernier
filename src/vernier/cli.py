"""vernier's command line.

Three commands, one measurement underneath. ``ablate`` ranks the segments whose
removal moves the answer, ``deadweight`` reports the same run inverted, and
``haze`` reads the shape of the distribution rather than its argmax.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Mapping, Sequence

from vernier.client import (
    DEFAULT_MODEL,
    ConfigurationError,
    HttpJevClient,
    JevClient,
    StubJevClient,
)
from vernier.report import render_deadweight, render_haze, render_json, render_text
from vernier import questions
from vernier.errors import VernierError
from vernier.questions import QuestionError
from vernier.run import Config, Report, ablate
from vernier.segment import SEGMENTERS
from vernier.types import Mode, Question

EXIT_OK = 0
EXIT_INVALID = 1
EXIT_USAGE = 2
EXIT_ERROR = 3


class UsageError(Exception):
    pass


def build_question(args: argparse.Namespace) -> Question:
    """Assemble the question from flags or a JSON spec.

    Raises:
        UsageError: If the flags do not describe exactly one well-formed question.
    """
    try:
        return _question_from(args)
    except QuestionError as exc:
        raise UsageError(str(exc)) from exc


def _question_from(args: argparse.Namespace) -> Question:
    if args.question_file:
        return questions.from_mapping(_load_spec(args.question_file))

    given = [bool(args.noul), bool(args.choice), bool(args.score)]
    if sum(given) != 1:
        raise UsageError("give exactly one of --noul, --choice, --score, or --question-file")

    if args.noul:
        return questions.noul(args.noul, true=args.true, false=args.false)
    if args.choice:
        return questions.choice(args.choice, _options(args.option))
    return questions.score(args.score, args.level)


def _load_spec(path: str) -> Mapping[str, object]:
    try:
        spec = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise UsageError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise UsageError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(spec, dict):
        raise UsageError(f"{path} must hold a JSON object describing one question")
    return spec


def _options(raw: Sequence[str]) -> dict[str, str | None]:
    """Parse repeated --option NAME[=DESCRIPTION] flags."""
    parsed: dict[str, str | None] = {}
    for item in raw:
        name, _, description = item.partition("=")
        if name in parsed:
            raise UsageError(f"duplicate option {name!r}")
        parsed[name] = description or None
    return parsed


def build_client(args: argparse.Namespace) -> JevClient:
    if args.stub:
        # Offline mode: the same pipeline, a synthetic instrument. Useful for
        # seeing the shape of a run, and for the test suite.
        return StubJevClient(
            base=args.stub_base,
            sensitive={args.stub_sensitive: args.stub_shift} if args.stub_sensitive else {},
            seed=args.stub_seed,
        )
    try:
        return HttpJevClient.from_environment(
            model=args.model, timeout=args.timeout, retries=args.retries
        )
    except ConfigurationError as exc:
        raise UsageError(str(exc)) from exc


def build_config(args: argparse.Namespace) -> Config:
    modes = tuple(Mode(m) for m in dict.fromkeys(args.mode))
    if args.baseline_calls < 2:
        raise UsageError("--baseline-calls must be at least 2 to measure a spread")
    if args.trial_calls < 1:
        raise UsageError("--trial-calls must be at least 1")
    return Config(
        segmentation=args.by,
        modes=modes,
        baseline_replicates=args.baseline_calls,
        perturbed_replicates=args.trial_calls,
        concurrency=args.concurrency,
        controls=0 if args.no_control else args.controls,
    )


def load_document(path: str) -> tuple[str, str]:
    if path == "-":
        return sys.stdin.read(), "<stdin>"
    try:
        return Path(path).read_text(encoding="utf-8"), path
    except OSError as exc:
        raise UsageError(f"cannot read {path}: {exc}") from exc


def execute(args: argparse.Namespace) -> Report:
    text, source = load_document(args.document)
    if not text.strip():
        raise UsageError("the document is empty")
    return ablate(
        text, build_question(args), build_client(args), build_config(args), source=source
    )


def _exit_code(report: Report) -> int:
    if report.aborted:
        return EXIT_INVALID
    if not report.validity.ok:
        return EXIT_INVALID
    return EXIT_OK


def cmd_ablate(args: argparse.Namespace) -> int:
    report = execute(args)
    print(render_json(report) if args.json else render_text(report))
    return _exit_code(report)


def cmd_deadweight(args: argparse.Namespace) -> int:
    report = execute(args)
    print(render_json(report) if args.json else render_deadweight(report))
    return _exit_code(report)


def cmd_haze(args: argparse.Namespace) -> int:
    report = execute(args)
    print(render_json(report) if args.json else render_haze(report))
    return _exit_code(report)


def build_parser() -> argparse.ArgumentParser:
    question = argparse.ArgumentParser(add_help=False)
    question.add_argument("--noul", metavar="QUESTION", help="a yes/no question")
    question.add_argument("--true", metavar="DESC", help="what a yes means")
    question.add_argument("--false", metavar="DESC", help="what a no means")
    question.add_argument("--choice", metavar="QUESTION", help="pick one option")
    question.add_argument(
        "--option", action="append", default=[], metavar="NAME[=DESC]", help="a Choice option"
    )
    question.add_argument("--score", metavar="QUESTION", help="rate against ordered levels")
    question.add_argument(
        "--level", action="append", default=[], metavar="LEVEL", help="a Score level, lowest first"
    )
    question.add_argument("--question-file", metavar="FILE", help="a JSON question spec")

    common = argparse.ArgumentParser(add_help=False, parents=[question])
    common.add_argument("document", help="the document to measure, or - for stdin")
    common.add_argument(
        "--by", default="section", choices=sorted(SEGMENTERS), help="segmentation (default: section)"
    )
    common.add_argument(
        "--mode",
        action="append",
        choices=[m.value for m in Mode],
        default=None,
        help="perturbation mode; repeatable (default: both)",
    )
    common.add_argument(
        "--baseline-calls", type=int, default=5, metavar="K", help="noise-floor replicates"
    )
    common.add_argument(
        "--trial-calls", type=int, default=3, metavar="K", help="replicates per perturbed variant"
    )
    common.add_argument("--controls", type=int, default=2, metavar="N", help="placebo segments")
    common.add_argument(
        "--no-control", action="store_true", help="skip the control condition (not recommended)"
    )
    common.add_argument("--concurrency", type=int, default=8, metavar="N")
    common.add_argument("--model", default=DEFAULT_MODEL)
    common.add_argument("--timeout", type=float, default=60.0, metavar="SECONDS")
    common.add_argument("--retries", type=int, default=4)
    common.add_argument("--json", action="store_true", help="emit the full measurement as JSON")
    common.add_argument("--stub", action="store_true", help="run offline against a synthetic model")
    common.add_argument("--stub-base", type=float, default=0.6, help=argparse.SUPPRESS)
    common.add_argument("--stub-sensitive", default=None, help=argparse.SUPPRESS)
    common.add_argument("--stub-shift", type=float, default=-0.4, help=argparse.SUPPRESS)
    common.add_argument("--stub-seed", type=int, default=0, help=argparse.SUPPRESS)

    parser = argparse.ArgumentParser(
        prog="vernier",
        description="Measure meaning by perturbing text and watching a calibrated probability move.",
        epilog=(
            "examples:\n"
            "  vernier ablate rulebook.md --noul 'Does this permit a permanent ban here?'\n"
            "  vernier haze contract.md --choice 'Who owns the IP?' "
            "--option client --option vendor\n"
            "  vernier deadweight policy.md --question-file q.json --by paragraph\n"
            "\n"
            "exit: 0 measured, 1 measurement invalid or aborted, 2 usage, 3 error\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)
    a = sub.add_parser(
        "ablate", parents=[common], help="rank segments by how far their removal moves the answer"
    )
    a.set_defaults(func=cmd_ablate)
    d = sub.add_parser(
        "deadweight", parents=[common], help="the same run inverted: segments that move nothing"
    )
    d.set_defaults(func=cmd_deadweight)
    h = sub.add_parser(
        "haze", parents=[common], help="read the shape of the distribution, not its argmax"
    )
    h.set_defaults(func=cmd_haze)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.mode is None:
        args.mode = [Mode.DELETE.value, Mode.MASK.value]
    try:
        return int(args.func(args))
    except UsageError as exc:
        print(f"vernier: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except KeyboardInterrupt:
        return 130
    except VernierError as exc:
        # Everything vernier raises deliberately. A traceback from anything
        # else is a bug, and swallowing it here would hide it.
        print(f"vernier: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
