"""Turns the report dict into the student-facing text report and writes the JSON one."""
from __future__ import annotations

import json
import re
import textwrap


def write_json(path, report):
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _show(s):
    return repr(s.rstrip("\n")) if s.strip() else "(empty)"


def _dedupe(counterexamples, limit):
    """Show one example per kind of failure (numbers collapsed), smallest inputs first."""
    shown, seen = [], set()
    for c in counterexamples:
        key = (c["category"].split(":")[0], re.sub(r"-?\d+", "N", c["why"]))
        if key not in seen:
            seen.add(key)
            shown.append(c)
    return shown[:limit]


def render_text(report, max_counterexamples=5):
    L = [f"===== Grading report for {report['submission']} =====",
         f"Overall grade: {report['grade']:.1f} / 100" + ("   [PARTIAL REPORT]" if report["partial"] else "")]
    L += [f"FLAG: {fl}" for fl in report["flags"]]
    L += ["", f"{'Metric':<15}{'Weight':>7}  {'Points':>9}  Note"]
    for m in report["metrics"]:
        pts = "n/a" if m["status"] in ("skipped_tool_missing", "analyzer_error") else \
            f"{m['contribution']:.1f}/{m['effective_weight'] * 100:.0f}"
        L.append(f"{m['name']:<15}{m['weight'] * 100:>6.0f}%  {pts:>9}  {m['feedback'][:90]}")

    ce = report["counterexamples"]
    if ce:
        shown = _dedupe(ce, max_counterexamples)
        L += ["", "--- Where you failed ---"]
        for c in shown:
            L += [f"[{c['category']}]", f"  INPUT:    {_show(c['input'])}",
                  f"  EXPECTED: {_show(c['expected'])}", f"  GOT:      {_show(c['got'])}"]
            L += ["  " + ln for ln in textwrap.wrap("WHY: " + c["why"], 74)]
        if len(ce) > len(shown):
            L.append(f"({len(ce)} failing inputs in total; similar ones omitted, see the JSON report.)")

    if report["suggestions"]:
        L += ["", "--- Suggestions to raise the grade ---"]
        for s in report["suggestions"]:
            L += textwrap.wrap("- " + s, 78, subsequent_indent="  ")

    summ = report.get("llm_summary")
    if summ and summ.get("text"):
        L += ["", f"--- Tutor summary (written by local model {summ['model']}; does not affect the grade) ---"]
        L += textwrap.wrap(summ["text"], 78)

    ul = report.get("usefulness_limitations")
    if ul:
        L += ["", "--- Usefulness & limitations of this evaluation ---", "Useful for:"]
        for i, u in enumerate(ul["usefulness"], 1):
            L.append(f" {i}. {u['use_case']}")
            for label, key in (("Example", "example"), ("Benefit", "benefit")):
                L += textwrap.wrap(f"{label}: {u[key]}", 74, initial_indent="    ", subsequent_indent="    ")
        L.append("Limits of this report:")
        for i, u in enumerate(ul["limitations"], 1):
            L.append(f" {i}. {u['limitation']}")
            for label, key in (("Example", "example"), ("Mitigation", "mitigation")):
                L += textwrap.wrap(f"{label}: {u[key]}", 74, initial_indent="    ", subsequent_indent="    ")
    return "\n".join(L) + "\n"
