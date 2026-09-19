"""Rendering. Every number is shown against the noise it had to beat."""

from __future__ import annotations

import json
from typing import Iterable, Sequence

from .distance import normalised_entropy
from .noise import ALPHA, Effect, Verdict
from .run import Report, Row, agreed_entropy_shift, baseline_haze
from .types import Reading

BAR = "█"
RULE = "─"

_MARK = {
    Verdict.CORROBORATED: "++",
    Verdict.MODE_SENSITIVE: "~ ",
    Verdict.INDETERMINATE: "? ",
    Verdict.NULL: "  ",
    Verdict.AT_RESOLUTION_LIMIT: "!!",
    Verdict.FAILED: "XX",
}


def _trim(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def _reading_str(r: Reading) -> str:
    if r.type == "noul":
        return f"p={r.answer:.2f}"
    parts = ", ".join(f"{k}={v:.2f}" for k, v in r.probs)
    conf = f" conf={r.confidence:.2f}" if r.confidence is not None else ""
    head = r.answer if isinstance(r.answer, str) else f"{r.answer:.2f}"
    return f"{head} [{parts}]{conf}"


def _bar(value: float, scale: float, width: int = 18) -> str:
    if scale <= 0:
        return ""
    filled = int(round(min(value / scale, 1.0) * width))
    return BAR * filled + "·" * (width - filled)


def render_text(report: Report, show_null: bool = True) -> str:
    out: list[str] = []
    w = 78
    out.append(RULE * w)
    out.append(f"vernier ablate — {report.source}")
    out.append(RULE * w)
    out.append(f"question   [{report.question.type}] {_trim(report.question.instructions, 60)}")
    content = [s for s in report.segments if not s.is_control]
    out.append(
        f"segments   {len(content)} by {report.config.segmentation}"
        f"  +{len(report.segments) - len(content)} control"
    )
    out.append(f"modes      {', '.join(m.value for m in report.config.modes)}")
    out.append(f"metric     {report.metric}   calls {report.calls}")
    out.append("")

    out.extend(_baseline_block(report))
    out.extend(_power_block(report))
    out.append("")

    if report.aborted:
        out.append(f"!! RUN ABORTED: {report.aborted}")
        out.append("")
        out.extend(_explain_abort(report))
        return "\n".join(out)

    out.extend(_control_block(report))
    out.append("")

    if not report.validity.ok:
        out.append("!! MEASUREMENT INVALID — no ranking is printed.")
        for reason in report.validity.reasons:
            out.append(f"   {reason}")
        out.append("")
        out.append(
            "   A control segment is unrelated boilerplate; removing it cannot change what"
        )
        out.append(
            "   this document says. That it moved the number means the reading is driven by"
        )
        out.append("   something other than meaning, so a ranking would be a confident guess.")
        return "\n".join(out)

    out.extend(_ranking_block(report))
    if show_null:
        out.append("")
        out.extend(_null_block(report))
    if report.failures:
        out.append("")
        out.append(f"!! {len(report.failures)} call(s) failed — affected rows are marked XX:")
        for f in report.failures[:5]:
            out.append(f"   {_trim(f, w - 3)}")
    return "\n".join(out)


def _baseline_block(report: Report) -> list[str]:
    out = ["BASELINE  (unmodified document, one call each)"]
    for i, r in enumerate(report.baseline):
        out.append(f"  [{i}] {_reading_str(r)}")
    if not report.baseline:
        out.append("  (none)")
        return out
    floor = report.floor
    out.append(f"  entropy    {baseline_haze(report):.3f} of maximum")
    out.append("")
    out.append("NOISE FLOOR  (spread across identical calls; nothing below it is a finding)")
    out.append(
        f"  measured spread   {floor.observed:.4f} {report.metric}"
        f"   over {len(floor.spreads)} pairs"
    )
    out.append(
        f"  resolution limit  {floor.quantization:.4f}"
        "   (probabilities arrive rounded to 2dp)"
    )
    out.append(f"  floor             {floor.value:.4f}   limited by {floor.limited_by}")
    out.append(
        f"  threshold         {floor.threshold:.4f}   floor + one resolution step"
    )
    out.append(
        f"  entropy spread    {floor.entropy_spread:.4f}   the floor haze is read against"
    )
    if floor.saturated:
        out.append(
            "  !! baseline is one-hot: the question has no headroom left to measure into."
        )
    return out


def _power_block(report: Report) -> list[str]:
    """Warn when the run could not have reached significance whatever it saw."""
    worst = [
        e
        for row in report.rows
        for e in row.effects.values()
        if e.ok and e.underpowered()
    ]
    if not worst:
        return []
    best_p = min(1.0 / e.permutations for e in worst)
    return [
        "",
        f"!! UNDERPOWERED: with these replicate counts the smallest reachable p-value is",
        f"   {best_p:.3f}, above the {ALPHA} threshold, so nothing can be established no",
        "   matter how far it moved. Raise --baseline-calls and --trial-calls.",
    ]


def _explain_abort(report: Report) -> list[str]:
    return [
        "   Every baseline replicate put all of its probability on one outcome, so the",
        "   measured spread is zero and the floor is the rounding grid. Ablation could",
        "   only flip the argmax or do nothing — the very reading this tool avoids.",
        "   Ask a question the document does not already settle, or widen the options.",
    ]


def _control_block(report: Report) -> list[str]:
    rows = report.validity.control_rows
    if not rows:
        return ["CONTROL   none injected — this run is uncontrolled."]
    out = ["CONTROL   (neutral segments that must land inside the noise)"]
    for row in rows:
        detail = "  ".join(
            f"{mode}={e.size:.4f} p={e.p_value:.3f}" if e.ok else f"{mode}=FAILED"
            for mode, e in row.effects.items()
        )
        # A control fails only when it *establishes* an effect. An
        # indeterminate control asserted nothing, so it invalidates nothing.
        failed = row.verdict in {
            Verdict.CORROBORATED,
            Verdict.MODE_SENSITIVE,
            Verdict.FAILED,
        }
        out.append(f"  [{'FAIL' if failed else 'pass'}] {_trim(row.segment.label, 26):<26} {detail}")
    out.append("  [pass] segmentation tiles the document byte-exactly (null ablation)")
    return out


def _scale(rows: Sequence[Row]) -> float:
    values = [e.size for r in rows for e in r.effects.values() if e.ok]
    return max(values) if values else 1.0


def _row_line(row: Row, scale: float, modes: Iterable[str]) -> list[str]:
    mark = _MARK[row.verdict]
    head = f" {mark} {_trim(row.segment.label, 36):<36}"
    per_mode = []
    for mode in modes:
        e = row.effects.get(mode)
        if e is None:
            continue
        if not e.ok:
            per_mode.append(f"      {mode:<7} failed: {_trim(e.error or '', 40)}")
            continue
        arrow = "↓" if e.direction < 0 else "↑"
        per_mode.append(
            f"      {mode:<7} {e.size:.4f}  p={e.p_value:.3f}  "
            f"{arrow}{abs(e.direction):.2f}  {_bar(e.size, scale)}"
        )
    return [head, *per_mode]


def _ranking_block(report: Report) -> list[str]:
    ranked = report.ranked
    out = [
        f"ATTRIBUTION  ({len(ranked)} of {len(report.content_rows)} segments cleared "
        f"{report.floor.threshold:.4f} at p\u2264{ALPHA})",
        "  ++ corroborated by both modes   ~ mode-sensitive (deletion confound suspected)",
        "  size = distance between mean baseline and mean perturbed distribution",
        "  p    = exact permutation test: could this run's jitter alone do it?",
        "",
    ]
    if not ranked:
        out.append("  Nothing cleared the noise floor. On this question, this document's")
        out.append("  verdict does not rest on any single segment.")
        return out
    scale = _scale(ranked)
    modes = [m.value for m in report.config.modes]
    for row in ranked:
        out.extend(_row_line(row, scale, modes))
    return out


def _interval(row: Row, modes: Iterable[str]) -> str:
    """Every mode's observed interval, so a straddle is visible as a straddle."""
    parts = []
    for mode in modes:
        e = row.effects.get(mode)
        if e is None:
            continue
        parts.append(
            f"{mode} {e.size:.4f} p={e.p_value:.3f}" if e.ok else f"{mode} FAILED"
        )
    return "   ".join(parts)


def _widest_size(row: Row) -> float:
    """The largest effect size any mode measured for this segment."""
    return max((e.size for e in row.effects.values() if e.ok), default=0.0)


def _detectable(row: Row) -> bool:
    """True when a mode separated this segment from jitter despite its small size."""
    return any(e.ok and e.p_value <= ALPHA for e in row.effects.values())


def _null_block(report: Report) -> list[str]:
    modes = [m.value for m in report.config.modes]
    out: list[str] = []
    undecided = report.indeterminate
    if undecided:
        out.append(f"INDETERMINATE  ({len(undecided)} segments — moved, but not established)")
        out.append(
            "  Some reading exceeded the floor, but the movement is either too small or"
        )
        out.append(
            "  too inconsistent to separate from jitter. Not a finding, and not deadweight."
        )
        for row in undecided:
            out.append(f"   ?  {_trim(row.segment.label, 40):<40} {_interval(row, modes)}")
        out.append("")
    rows = report.inside_noise
    out.append(
        f"INSIDE THE NOISE  ({len(rows)} segments — effect under "
        f"{report.floor.threshold:.4f} in both modes)"
    )
    for row in rows:
        out.append(f"      {_trim(row.segment.label, 40):<40} {_interval(row, modes)}")
    return out


def render_deadweight(report: Report) -> str:
    """Ablate, read inverted: what the verdict does not rest on."""
    out = render_text(report, show_null=False).split("\n")
    if report.aborted or not report.validity.ok:
        return "\n".join(out)
    modes = [m.value for m in report.config.modes]
    rows = report.inside_noise
    out.append("")
    out.append(f"DEADWEIGHT  ({len(rows)} of {len(report.content_rows)} segments)")
    out.append(
        f"  Removing any of these moved the answer by less than {report.floor.threshold:.4f}"
    )
    out.append(
        f"  {report.metric}, the floor this run measured, under both perturbation modes"
    )
    out.append("  and with enough replicates to have seen a larger effect.")
    out.append("")
    if not rows:
        out.append("  None. Every segment carries measurable weight on this question.")
    else:
        scale = _scale(report.content_rows) or 1.0
        for row in rows:
            size = _widest_size(row)
            note = " (real but negligible)" if _detectable(row) else ""
            out.append(
                f"      {_trim(row.segment.label, 38):<38} \u2264{size:.4f}"
                f"  {_bar(size, scale, 12)}{note}"
            )
        if any(_detectable(r) for r in rows):
            out.append("")
            out.append(
                "  'real but negligible' means the movement repeated too consistently to"
            )
            out.append(
                "  be jitter, and is still smaller than this run can call meaningful."
            )
    undecided = report.indeterminate
    if undecided:
        out.append("")
        out.append(
            f"  NOT deadweight, and not a finding either ({len(undecided)}): these moved"
        )
        out.append("  further than the floor without repeating consistently enough to assert.")
        for row in undecided:
            out.append(f"   ?  {_trim(row.segment.label, 38):<38} {_interval(row, modes)}")
    out.append("")
    out.append("  Deadweight is a claim about this question only. A segment that is inert")
    out.append("  here may carry the whole verdict on another.")
    return "\n".join(out)


def render_haze(report: Report) -> str:
    """Read the shape of the distribution, not its argmax."""
    w = 78
    out = [RULE * w, f"vernier haze — {report.source}", RULE * w]
    out.append(f"question   [{report.question.type}] {_trim(report.question.instructions, 60)}")
    out.append(f"metric     {report.metric}   calls {report.calls}")
    out.append("")
    out.extend(_baseline_block(report))
    out.append("")
    haze = baseline_haze(report)
    out.append(f"HAZE  {haze:.3f}   {_bar(haze, 1.0, 30)}")
    out.append("")
    out.extend(_haze_verdict(haze, report))
    if report.aborted:
        return "\n".join(out)
    out.append("")
    out.extend(_haze_by_segment(report))
    return "\n".join(out)


def _haze_verdict(haze: float, report: Report) -> list[str]:
    if report.question.type != "noul" and len(report.baseline) and report.baseline[0].confidence:
        conf = report.baseline[0].confidence
        tail = [f"  Jev's own confidence: {conf:.2f}."]
    else:
        tail = ["  (A Noul reports no confidence; the spread of p is the whole shape.)"]
    if haze >= 0.85:
        head = [
            "  The distribution is close to flat. With well-formed options that is a fact",
            "  about the input, not the model: this document does not decide the question.",
        ]
    elif haze >= 0.4:
        head = [
            "  The distribution is spread but leaning. The document points somewhere",
            "  without settling it.",
        ]
    else:
        head = ["  The distribution is concentrated. The document decides this question."]
    return head + tail


def _haze_by_segment(report: Report) -> list[str]:
    """Where the ambiguity lives: which removals sharpen or blur the reading."""
    floor = report.floor.entropy_spread
    out = [
        "WHERE THE AMBIGUITY LIVES  (change in entropy when a segment is removed)",
        "  sharpens = removing it left the reading more decided, so that section was a",
        "  source of the ambiguity.  blurs = it was helping to resolve the question.",
        f"  entropy noise floor {floor:.3f}: the baseline's own entropy wanders this much",
        "  between identical calls, so smaller shifts are not reported. Only shifts both",
        "  perturbation modes agree on, in direction and size, are counted.",
        "",
    ]
    scored: list[tuple[float, Row]] = []
    for row in report.content_rows:
        shift = agreed_entropy_shift(row)
        if shift is not None and abs(shift) > floor:
            scored.append((shift, row))
    if not scored:
        out.append("  No segment shifted the entropy further than the baseline shifts on")
        out.append("  its own. The ambiguity is spread across this document rather than")
        out.append("  located in any one section.")
        return out
    for shift, row in sorted(scored, key=lambda pair: abs(pair[0]), reverse=True)[:10]:
        label = "sharpens" if shift < 0 else "blurs   "
        out.append(
            f"      {_trim(row.segment.label, 40):<40} {label} {shift:+.3f}"
            f"  {_bar(abs(shift), 1.0, 12)}"
        )
    return out


def _effect_json(e: Effect) -> dict[str, object]:
    return {
        "ok": e.ok,
        "error": e.error,
        "size": e.size,
        "p_value": e.p_value,
        "permutations": e.permutations,
        "underpowered": e.underpowered(),
        "low": e.low,
        "high": e.high,
        "distances": list(e.distances),
        "entropy_delta": e.entropy_delta,
        "confidence_delta": e.confidence_delta,
        "direction": e.direction,
    }


def render_json(report: Report) -> str:
    payload: dict[str, object] = {
        "source": report.source,
        "question": report.question.payload(),
        "metric": report.metric,
        "segmentation": report.config.segmentation,
        "modes": [m.value for m in report.config.modes],
        "calls": report.calls,
        "usage": dict(report.usage),
        "aborted": report.aborted,
        "baseline": [
            {
                "type": r.type,
                "answer": r.answer,
                "probabilities": dict(r.probs),
                "confidence": r.confidence,
                "normalised_entropy": normalised_entropy(r.distribution),
            }
            for r in report.baseline
        ],
        "noise_floor": {
            "metric": report.floor.metric,
            "observed_spread": report.floor.observed,
            "resolution_limit": report.floor.quantization,
            "floor": report.floor.value,
            "threshold": report.floor.threshold,
            "limited_by": report.floor.limited_by,
            "saturated": report.floor.saturated,
            "at_resolution_limit": report.floor.at_resolution_limit,
            "pairwise_spreads": list(report.floor.spreads),
        },
        "validity": {
            "ok": report.validity.ok,
            "reasons": list(report.validity.reasons),
        },
        "segments": [
            {
                "index": row.segment.index,
                "label": row.segment.label,
                "kind": row.segment.kind.value,
                "characters": len(row.segment.text),
                "verdict": row.verdict.value,
                "strength": row.strength,
                "rank": next((i + 1 for i, r in enumerate(report.ranked) if r is row), None),
                "effects": {m: _effect_json(e) for m, e in row.effects.items()},
            }
            for row in report.rows
        ],
        "failures": list(report.failures),
    }
    return json.dumps(payload, indent=2)
