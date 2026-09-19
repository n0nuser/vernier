# Working on vernier

vernier is an **instrument**. It reports a number and a claim about whether that
number means anything. Code that makes the number prettier at the cost of the
claim is a regression here, however green the suite is.

Read `README.md` for what the tool does and why. This file is what the code
cannot tell you by looking.

## The measurement, in one paragraph

Jev answers a question about a document and returns a probability
*distribution*. Remove one segment, ask again, and measure how far the
distribution moved. Repeat per segment. A movement counts as a finding only if
it clears the **floor** — how far the number drifts between identical calls —
and survives a permutation test against that same jitter.

## Invariants

These hold across every change. The suite checks most of them; it cannot check
all of them, which is why they are written down.

**The floor is never zero.** Jev reports probabilities rounded to two decimals.
Identical calls returning identical numbers means the jitter sits below the
grid, not that there is none. `resolution_limit()` is the lower bound and it
applies always. A floor of zero would make every rounding artefact a finding —
the exact failure this tool exists to prevent.

**Estimators converge.** More replicates sharpen a result; they never widen it.
This is the bug class that has bitten twice: `min` over cross-pairs and `max`
over cross-pairs both drift *outward* as samples grow, so more data made
findings weaker and deadweight impossible. Effects are measured between group
means, which converge. Before you land a change to any statistic, run it at k
and at 2k replicates and confirm the finding sharpens.

**A finding clears two hurdles.** Effect size above the floor, *and* a
permutation p-value at or under alpha. Size alone reports jitter; significance
alone reports a perfectly repeatable half-step of the grid. Both, or it is not a
finding.

**A failed call stays a failure.** It never becomes a zero delta. A segment
nobody could measure is neither a finding nor deadweight, it is `Verdict.FAILED`,
and it appears by name in the report body. Silently scoring it zero would say
"this segment does not matter" about a segment nobody measured — the worst thing
this tool could say.

**Controls decide whether a ranking is printed at all.** Placebo sections are
injected into the document and ablated like any other. If one moves the number
beyond the floor, the run prints its reasons and no ranking. Keep that gate
ahead of any output path you add.

**Segmenters tile byte-exactly.** The spans a segmenter returns reconstruct the
document exactly, and `verify_tiling` enforces it. That is the null-ablation
control, done statically: a segmenter that cannot rebuild its input is measuring
itself.

**Distributions, not argmaxes.** Compare whole distributions — `tvd` for Noul,
`jsd` for Choice and Score. A segment can reshape a distribution without moving
which option wins, and that reshaping is the signal.

## Where the risk is

`noise.py` and `distance.py` carry the claims. A change there can be wrong in a
way the suite still passes, because the suite mostly checks that the plumbing
runs. When you touch either, say in the commit message which invariant you
checked and how.

`report.py` composes. `render_deadweight` wraps the whole of `render_text`, and
`render_haze` shares `_baseline_block` with it, so a block added in one place
surfaces in views you were not editing — which has already printed one section
twice. After changing rendering, run all three commands and read the output.

## Fixtures

`examples/contributor-covenant-2.1.md` is the measured artifact and stays
byte-faithful. A licence header added to the top of it became a segment the tool
then ablated, and a test caught it. Notes about that file live in
`examples/README.md`, beside it. It is CC BY 4.0, unlike the rest of the repo.

`StubJevClient` reproduces the three API behaviours the statistics have to
survive: answers on a two-decimal grid, identical calls that differ slightly,
and distributions that saturate at 1.0. Tests run against it, so the suite needs
no network and no key. Keep it that way — `tests/` never reaches the API.

## Making a change

1. Write the test first when the change is behavioural. The suite is the record
   of what the instrument promises.
2. `uv run pytest`, `uv run mypy` and `uv run ruff check .` all clean. mypy runs
   strict over `src` and `tests`.
3. If you touched a statistic, run the convergence check above.
4. If you touched rendering, run `ablate`, `deadweight` and `haze` and read
   what they print.
5. Commit message says what changed and why it was wrong before. The history
   here explains reasoning, not just diffs.

Done means: suite green, mypy and ruff clean, and every invariant your change
touches re-verified by running something — not by reasoning about it.

## Conventions

`ruff check .` gates absolute imports, import order, docstring format, line
length and the rest. It runs in CI beside `pytest` and `mypy`, and all three
have to be clean.

Two rules are tuned, both for a stated reason in `pyproject.toml`: `D1xx` is off
because the gate enforces docstring *format*, never presence, and `PLR2004` is
off because it fires on structural minimums like `if len(levels) < 2`, where the
literal states the rule better than a name for it would. Thresholds that are not
self-evident carry names — `HAZE_FLAT`, `ONE_HOT_TOLERANCE`,
`STEADY_BASELINE_REPLICATES`.

These need a human:

- Comments explain **why**. Naming carries the what.
- Docstrings appear where they add what a signature cannot say, not on
  everything.
- Errors inherit `VernierError`, so one `except` catches the library and nothing
  else. Specific errors live beside the code that raises them.
- I/O stays at the edges. `client.py` is the only module that reaches the
  network; nothing reads the environment except `HttpJevClient.from_environment`.
  Importing the package touches nothing.
- The public surface is the `__all__` in `__init__.py`. Adding to it is a
  promise; check `tests/test_public_api.py` still passes.

## Releasing

The tag is the release. `git tag v0.1.2 && git push origin v0.1.2` runs the
suite, sets the version in `pyproject.toml` from the tag, and publishes to PyPI
through Trusted Publishing. No token exists in the repo or its secrets. The
workflow refuses to upload if the artifacts disagree with the tag, or if PyPI
already has that version — a version number can never be reused.

The pipeline sets that version in its own checkout and does not commit it back,
so after a release bump `pyproject.toml` on `main` to match what shipped. It is
a record of the last release, not the input to the next one: the tag is.

## Not in the repository, on purpose

`.review/` holds a filled review ledger that reproduces another project's
private engineering standards. It is gitignored and was purged from history.
Keep it out.
