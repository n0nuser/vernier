# vernier

Measure meaning by perturbing text and watching a calibrated probability move.

`vernier` is built on [TypeSafe's Jev](https://docs.typesafe.ai), a System One
model that returns typed judgments with calibrated probability distributions
instead of generated text. Everyone uses Jev's answer and throws the
distribution away. The distribution is the measurement.

Remove one section of a document, ask the same question again, and see how far
the distribution moved. Repeat for every section. What comes back is an
attribution map: which parts of this document are actually carrying its verdict.
This is occlusion testing, borrowed from computer vision and pointed at meaning.

## The problem with doing that naively

Any tool can delete a paragraph and print a delta. The number will be wrong, for
four reasons, and `vernier` exists to handle all four.

**The model is not deterministic.** Ask Jev the same question five times and the
answer moves. On the example below the baseline wanders between 0.80 and 0.82.
Any delta smaller than that wander is not a finding, it is the instrument
breathing. So `vernier` measures the baseline *k* times before it perturbs
anything, and reports every result against that floor.

**A measured spread of zero is not a noise floor of zero.** Jev reports
probabilities rounded to two decimals. Five identical readings tell you the
jitter is below the grid, not that there is none — and if the baseline is
saturated at 1.00, every nonzero delta would "beat" a floor of zero and the tool
would confidently rank rounding error. The floor is therefore never below the
resolution limit, and a saturated baseline aborts the run instead of ranking it.

**Deletion is a confound.** Cutting text out makes the document shorter, can
orphan a heading and can break the grammar of what remains. All three move the
number for reasons that have nothing to do with meaning. So `vernier` also runs
a second mode that replaces the segment with length-matched neutral filler,
keeping the shape and swapping only the words. Where the two modes disagree, it
says so rather than picking the flattering one.

**The argmax is the wrong thing to watch.** A segment can reshape a whole
distribution without flipping which option wins. `vernier` compares
distributions — `|Δp|` for Noul, Jensen-Shannon for Choice and Score — and
reports entropy and Jev's own confidence alongside.

And one thing that is not a statistic: the tool ablates neutral control sections
it injected itself. They cannot change what the document says. If one of them
moves the number, `vernier` prints no ranking at all.

## Install

```sh
uv add vernier          # as a library
uv tool install vernier # as a command
export TYPESAFE_API_KEY=...   # from console.typesafe.ai/keys
```

## As a library

The CLI is a thin adapter over the same measurement. Everything it does is
importable, and nothing is read from the environment, logged or printed unless
you ask for it — the client is passed in, and rendering is a separate step.

```python
import vernier

report = vernier.ablate(
    text=open("policy.md").read(),
    question=vernier.noul("Does this policy permit a refund here?"),
    client=vernier.HttpJevClient.from_environment(),
)

if not report.validity.ok:
    raise SystemExit(report.validity.reasons[0])   # a control moved; do not trust a ranking

for row in report.ranked:
    print(f"{row.strength:.4f}  {row.verdict.value:14}  {row.segment.label}")
```

`noul`, `choice` and `score` build the three question types, mirroring
TypeSafe's own SDKs. `Report` carries `ranked`, `inside_noise`, `indeterminate`
and `unmeasured`, plus the `floor` every one of them was judged against.

Swap the client to run the whole pipeline with no network and no key — this is
how vernier's own test suite runs:

```python
report = vernier.ablate(text, question, vernier.StubJevClient(base=0.8))
```

Any object with an `evaluate(Call) -> Outcome` method satisfies `JevClient`, so
a recorded fixture, a cache or a different model drops straight in.

The statistics and the segmenters are usable on their own:

```python
vernier.segment(text, "section")          # also paragraph, sentence, line, item
vernier.tvd(before, after)                # and jsd, entropy, normalised_entropy
vernier.resolution_limit(3, "jsd")        # the floor 2dp rounding alone imposes
```

Errors all descend from `vernier.VernierError`, so one `except` covers the
library and nothing else. The package ships `py.typed`; a strict `mypy` run
against the public surface passes.

## A real measurement

The Contributor Covenant 2.1 is in `examples/`. It has a four-rung consequence
ladder, so it is a good document to ask a proportionality question of:

> A contributor has, over several months and after a prior written warning,
> repeatedly made derogatory remarks about contributors of a particular
> nationality. Under this Code of Conduct, is a permanent ban the proportionate
> consequence?

```sh
vernier ablate examples/contributor-covenant-2.1.md \
  --question-file examples/permanent-ban.json \
  --baseline-calls 8 --trial-calls 6
```

```
BASELINE  (unmodified document, one call each)
  [0] p=0.82   [1] p=0.80   [2] p=0.82   [3] p=0.81
  [4] p=0.80   [5] p=0.82   [6] p=0.81   [7] p=0.82

NOISE FLOOR  (spread across identical calls; nothing below it is a finding)
  measured spread   0.0200 tvd   over 28 pairs
  resolution limit  0.0100   (probabilities arrive rounded to 2dp)
  floor             0.0200   limited by run-to-run spread
  threshold         0.0300   floor + one resolution step

CONTROL   (neutral segments that must land inside the noise)
  [pass] ## Building Access         delete=0.0058 p=0.359  mask=0.0108 p=0.134
  [pass] ## Facilities Housekeeping delete=0.0158 p=0.005  mask=0.0025 p=0.800
  [pass] segmentation tiles the document byte-exactly (null ablation)

ATTRIBUTION  (4 of 12 segments cleared 0.0300 at p≤0.05)
 ++ ### 4. Permanent Ban
      delete  0.2042  p=0.000  ↓0.20  ██████████████████
      mask    0.1908  p=0.000  ↓0.19  █████████████████·
 ++ ### 3. Temporary Ban
      delete  0.0708  p=0.000  ↑0.07  ██████············
      mask    0.0692  p=0.000  ↑0.07  ██████············
 ++ ### 1. Correction
      delete  0.0342  p=0.000  ↑0.03  ███···············
      mask    0.0375  p=0.000  ↑0.04  ███···············
 ~  ### 2. Warning
      delete  0.0558  p=0.000  ↑0.06  █████·············
      mask    0.0192  p=0.002  ↑0.02  ██················
```

Read the arrows. Removing **Permanent Ban** takes the verdict *down* by 0.20 —
that section is what the verdict rests on. Removing any of the three milder
rungs pushes it *up*. The lesser consequences are competing alternatives, and
deleting a competitor makes the harsh answer look more proportionate. The ladder
behaves like a ladder, and nobody had to tell the tool that.

Everything else in the document — the pledge, the scope, the standards, the
enforcement sections, the attribution — is inside the noise on this question.
`## Our Standards` establishes that the conduct is a violation, but it has
nothing to say about *which rung*, and the measurement shows that.

`### 2. Warning` is marked `~`: deleting it moves the number three times as far
as masking it does. That is the deletion confound made visible, and it is
reported rather than ranked as if it were solid.

## The other two readings

`deadweight` is the same run inverted — the segments the verdict does not rest
on, with the ones that moved detectably but negligibly called out separately.

`haze` reads the shape of the distribution rather than its argmax. Asked whether
off-platform conduct falls within the Code of Conduct's scope, Jev answers
`out_of_scope` on all eight baseline calls — and the distribution is nearly
flat:

```
HAZE  0.850   █████████████████████████·····
  Jev's own confidence: 0.43.

WHERE THE AMBIGUITY LIVES  (change in entropy when a segment is removed)
      ### 2. Warning                           sharpens -0.085
      ## Enforcement Responsibilities          sharpens -0.072
```

The answer looks decisive and is not. `## Enforcement Responsibilities` lets
leaders act on anything they "deem inappropriate", which pulls against the
narrow `## Scope` section — and removing it measurably settles the question.
Given well-formed options, a flat distribution is a fact about the *input*, not
the model: the document does not decide this.

## Verdicts

| | |
|---|---|
| `++` corroborated | Above the floor under both modes, same direction. A finding. |
| `~` mode-sensitive | Above the floor under one mode only. The deletion confound, visible. |
| `?` indeterminate | Moved further than the floor without repeating consistently enough to assert. |
| *(none)* null | Effect below the floor in both modes, with the power to have seen more. |
| `XX` failed | A call did not come back. Never silently a zero. |

A finding has to clear two independent hurdles. **Effect size** must exceed the
noise floor — a movement smaller than the difference between two identical calls
is not worth reporting. And an exact **permutation test** must rule out this
run's jitter: pool the baseline and perturbed readings, and count how often a
random split separates the means as far as the real one did. Both statistics use
the mean distribution of each group, so both sharpen as replicates increase.

A big move measured once proves nothing. A perfectly repeatable move of half a
grid step is not worth knowing. Both hurdles, or it is not a finding.

## Usage

```
vernier ablate     DOCUMENT  rank segments by how far their removal moves the answer
vernier deadweight DOCUMENT  the same run inverted: segments that move nothing
vernier haze       DOCUMENT  read the shape of the distribution, not its argmax
```

Ask with `--noul QUESTION`, `--choice QUESTION --option a --option b`,
`--score QUESTION --level low --level high`, or `--question-file spec.json`.

| flag | |
|---|---|
| `--by` | `section` (default), `paragraph`, `sentence`, `line`, `item` |
| `--mode` | `delete`, `mask`; repeatable, both by default |
| `--baseline-calls K` | noise-floor replicates (default 5; 8 or more gives a steadier floor) |
| `--trial-calls K` | replicates per perturbed variant (default 3) |
| `--controls N` | placebo segments to inject (default 2) |
| `--no-control` | skip the control condition — the report will say the run is uncontrolled |
| `--json` | the whole measurement, including every replicate |
| `--stub` | run the entire pipeline offline against a synthetic model |

Exit codes: `0` measured, `1` invalid or aborted, `2` usage, `3` error.

A run is `segments × modes × trial-calls + baseline-calls` requests. Ablation
varies the state, so each variant must be its own request — there is nothing to
batch. Concurrency is bounded, retries follow the documented back-off, and a
failed call becomes a marked failure rather than a convenient zero.

## Layout

| module | |
|---|---|
| `__init__.py` | the public surface: a re-export facade, nothing else |
| `questions.py` | `noul` / `choice` / `score` constructors |
| `segment.py` | pluggable segmenters; every one tiles the document byte-exactly |
| `perturb.py` | delete and mask, plus placebo injection |
| `filler.py` | the neutral corpus both of those draw on |
| `client.py` | the System One client, and the stub that stands in for it |
| `distance.py` | TVD, Jensen-Shannon, entropy, and the resolution limit |
| `noise.py` | the noise floor, the permutation test, and the verdicts |
| `run.py` | orchestration: baseline, preflight, fan-out, assembly |
| `report.py` | rendering |
| `errors.py` | `VernierError`, the base every other error inherits |
| `cli.py` | argument parsing and exit codes; no measurement logic |

```sh
uv run pytest      # no network, no key
uv run mypy
```

The suite runs entirely against `StubJevClient`, which reproduces the three
quirks the statistics have to survive: answers on a two-decimal grid, identical
calls that differ slightly, and distributions that can saturate at 1.0.
