#!/usr/bin/env python3
"""The main agent (coordinator).

    python coordinator.py submissions/add.c                 # grade one file
    python coordinator.py samples/*.c --out reports         # grade many
    python coordinator.py submissions/add.c --no-llm        # skip Ollama entirely

Flow (same as the assignment): validate rules -> first pass (compile, smoke run, static sanity) ->
dispatch to the analyzers -> weighted collation -> JSON + text report.
Execution-based analyzers run one after another, because parallel load would make the wall-clock
limits flaky and the grade non-reproducible; source-only analyzers run in parallel afterwards.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import sandbox                                              # noqa: E402
from analyzers import REGISTRY                              # noqa: E402
from check_rules import RulesError, load_rules, with_defaults  # noqa: E402
from context import Context, load_reference                 # noqa: E402
from llm import OllamaClient                                # noqa: E402
from report import render_text, write_json                  # noqa: E402

READERS = r"\b(scanf|fscanf|sscanf|fgets|getchar|getline|read|fread|gets)\s*\("
WRITERS = r"\b(printf|fprintf|puts|putchar|fputs|fwrite|write)\s*\("


def tool_versions():
    v = {"gcc": sandbox.tool_version(["gcc", "--version"]),
         "valgrind": sandbox.tool_version(["valgrind", "--version"]),
         "cppcheck": sandbox.tool_version(["cppcheck", "--version"]) if shutil.which("cppcheck")
         else "not installed (skipped)",
         "python": sys.version.split()[0]}
    try:
        import lizard
        v["lizard"] = getattr(lizard, "version", "installed")
    except ImportError:
        v["lizard"] = "not installed (builtin fallback used)"
    return v


def sanity_check(ctx, compile_flags):
    """First pass: compile, smoke-run the sample input, static sanity. Returns (dict, binary|None)."""
    src = ctx.source
    fp = {"compiled": False, "compile_warnings": 0, "smoke_ok": False, "smoke_status": None,
          "suspected_infinite_loop": False,
          "static_sanity": {"has_main": bool(re.search(r"\bmain\s*\(", src)),
                            "has_reader": bool(re.search(READERS, src)),
                            "has_writer": bool(re.search(WRITERS, src)),
                            "has_return_in_main": bool(re.search(r"\breturn\b", src))}}
    binary = ctx.workdir / "main_bin"
    c = sandbox.compile_c(ctx.src, binary, compile_flags)
    fp["compile_warnings"] = len(re.findall(r": warning:", c["stderr"]))
    fp["compiled"] = c["ok"]
    if not c["ok"]:
        fp["compile_error"] = [re.sub(r"^.*?([\w.\-]+\.c:)", r"\1", ln) for ln in c["stderr"].strip().splitlines()[:5]]
        return fp, None
    res = sandbox.run_binary(binary, ctx.ref.SAMPLE_INPUT, ctx.time_limit, ctx.mem_mb)
    fp["smoke_status"] = res["status"]
    fp["smoke_ok"] = res["status"] == "ok"
    fp["suspected_infinite_loop"] = res["status"] == "timeout"
    return fp, binary


def run_metric(analyzer, ctx, params):
    spec = REGISTRY[analyzer]
    try:
        out = spec["fn"](ctx, with_defaults(spec["params"], params))
    except Exception as e:  # an analyzer bug must not sink the whole run
        return {"score": None, "status": "analyzer_error", "suggestions": [],
                "evidence": {"error": f"{type(e).__name__}: {e}"},
                "feedback": "Analyzer crashed; metric excluded.", "flags": [f"analyzer_error:{analyzer}"]}
    out.setdefault("evidence", {})
    out.setdefault("suggestions", [])
    out.setdefault("flags", [])
    out["flags"] = [f for f in out["flags"] if f]
    out["status"] = "ok" if out.get("score") is not None else "skipped_tool_missing"
    return out


def explain_failure(ref, inp, expected, got, note):
    if got.startswith("(timeout"):
        return "The program did not finish within the time limit on this input (infinite loop or far too slow)."
    if got.startswith("(crashed") or got.startswith("(exit code"):
        extra = f" Diagnostic: {note[:160]}" if note else ""
        return f"The program terminated abnormally {got} on this input.{extra}"
    return ref.explain(inp, expected, got, note)


def _llm_summary(ctx, report):
    facts = {"grade": report["grade"],
             "metrics": [{"name": m["name"], "points": f"{m['contribution']:.1f}/{m['effective_weight'] * 100:.0f}",
                          "feedback": m["feedback"][:160]} for m in report["metrics"]],
             "failing_example": ({k: report["counterexamples"][0][k] for k in ("input", "expected", "got", "why")}
                                 if report["counterexamples"] else None),
             "flags": report["flags"]}
    system = ("You are a friendly teaching assistant. Using ONLY the JSON facts, write 3-5 plain sentences "
              "telling the student what to fix first and why. Do not invent facts or change the grade. "
              'Reply with JSON only: {"summary": "<text>"}')
    res = ctx.llm.chat_json(system, json.dumps(facts, indent=1, sort_keys=True))
    text = res["data"].get("summary") if res["ok"] and isinstance(res["data"].get("summary"), str) else None
    return {"text": text.strip(), "model": res["model"]} if text else None


def grade(src_path, rules_path=None, out_dir=None, *, progress=None, use_llm=True, root=ROOT):
    """Grade one submission. `progress(event: dict)` is called from the calling thread only."""
    root = Path(root)
    rules_path = Path(rules_path or root / "rules.json")
    out_dir = Path(out_dir or root / "reports")
    log = []

    def step(stage, message, store=True, **extra):
        if store:
            log.append(f"[{stage}] {message}")
        if progress:
            progress({"stage": stage, "message": message, **extra})

    if not sandbox.SUPPORTED:
        raise EnvironmentError(sandbox.UNSUPPORTED_MSG)
    rules, rules_hash, rule_warnings = load_rules(rules_path, root)
    metrics = [m for m in rules["metrics"] if m.get("enabled", True)]
    for m in metrics:
        m.setdefault("name", m["analyzer"])
        m.setdefault("params", {})
    step("rules", f"{rules_path.name}: {len(metrics)} metrics, weights sum to 1.00")

    llm_cfg = dict(rules.get("llm", {}))
    if not use_llm:
        llm_cfg["enabled"] = False
    llm = OllamaClient(llm_cfg, cache_dir=root / ".cache" / "llm")
    llm_ok, llm_msg = llm.status()
    step("llm", llm_msg, ok=llm_ok)

    src_path = Path(src_path).resolve()
    source = src_path.read_text(errors="replace")
    ref = load_reference(root / rules["problem"]["reference"])
    with tempfile.TemporaryDirectory(prefix="autograder_") as td:
        ctx = Context(root=root, src=src_path, source=source, binary=None, workdir=Path(td),
                      rules=rules, ref=ref, llm=llm)
        fp, binary = sanity_check(ctx, rules.get("first_pass", {}).get("compile_flags", "-O2 -Wall -Wextra -std=c11"))
        ctx.binary, ctx.first_pass = binary, fp
        if not fp["compiled"]:
            step("first_pass", "compilation FAILED; execution-based analyzers will be skipped", ok=False)
        elif fp["suspected_infinite_loop"]:
            step("first_pass", "smoke run timed out: suspected_infinite_loop; execution-based analyzers skipped", ok=False)
        elif not fp["smoke_ok"]:
            step("first_pass", f"compiled, smoke run ended with {fp['smoke_status']}", ok=False)
        else:
            step("first_pass", f"compiled ({fp['compile_warnings']} warning(s)), smoke run OK", ok=True)
        blocked = (not fp["compiled"]) or fp["suspected_infinite_loop"]
        reason = "does not compile" if not fp["compiled"] else "suspected infinite loop (smoke run timed out)"

        flags = ["suspected_infinite_loop"] if fp["suspected_infinite_loop"] else []
        if not fp["compiled"]:
            flags.append("compile_failed")
        results = {}

        def record(m, res):
            results[m["name"]] = res
            sc = "n/a" if res["score"] is None else f"{res['score']:.2f}"
            # streamed live to the UI, but stored in the log later in rules order: source-only
            # analyzers finish in a nondeterministic order and the report must be byte-identical
            step("dispatch", f"{m['name']} ({m['analyzer']}) -> {res['status']}, score {sc}",
                 store=False, metric=m["name"], status=res["status"])

        for m in (x for x in metrics if REGISTRY[x["analyzer"]]["needs_execution"]):
            if blocked:
                record(m, {"score": 0.0, "status": "skipped_first_pass", "suggestions": [], "flags": [],
                           "evidence": {"skipped": reason}, "feedback": f"Skipped: {reason}."})
            else:
                record(m, run_metric(m["analyzer"], ctx, m["params"]))
        src_only = [x for x in metrics if not REGISTRY[x["analyzer"]]["needs_execution"]]
        with ThreadPoolExecutor(max_workers=4) as pool:
            futs = {pool.submit(run_metric, m["analyzer"], ctx, m["params"]): m for m in src_only}
            for fut in as_completed(futs):
                record(futs[fut], fut.result())

        for m in metrics:
            r = results[m["name"]]
            sc = "n/a" if r["score"] is None else f"{r['score']:.2f}"
            log.append(f"[dispatch] {m['name']} ({m['analyzer']}) -> {r['status']}, score {sc}")

        # ---- collation: weighted sum over the metrics that actually ran
        included = [m for m in metrics if results[m["name"]]["status"] in ("ok", "skipped_first_pass")]
        wsum = sum(m["weight"] for m in included) or 1.0
        metrics_out, total, suggestions = [], 0.0, []
        for m in metrics:
            r = results[m["name"]]
            inc = r["status"] in ("ok", "skipped_first_pass")
            eff = m["weight"] / wsum if inc else 0.0
            contrib = round(eff * (r["score"] or 0.0) * 100, 4) if inc else 0.0
            total += contrib
            flags.extend(r["flags"])
            if inc and r["score"] < 1:
                suggestions.extend(s for s in r["suggestions"] if s not in suggestions)
            metrics_out.append({"name": m["name"], "analyzer": m["analyzer"], "status": r["status"],
                                "score": None if r["score"] is None else round(r["score"], 4),
                                "weight": m["weight"], "effective_weight": round(eff, 4),
                                "contribution": round(contrib, 2), "evidence": r["evidence"],
                                "feedback": r["feedback"]})

        # ---- counter-examples: merge failing inputs from every analyzer, smallest first
        san = {}
        for m in metrics_out:
            for f in (m["evidence"].get("findings") or {}).values():
                san.setdefault(f["input"], f["message"])
        seen, cex = set(), []
        for m in metrics_out:
            for f in m["evidence"].get("failing") or []:
                if f["input"] in seen:
                    continue
                seen.add(f["input"])
                note = f.get("note") or san.get(f["input"], "")
                cex.append({"category": f["category"], "input": f["input"], "expected": f["expected"],
                            "got": f["got"], "note": note,
                            "why": explain_failure(ref, f["input"], f["expected"], f["got"], note)})
        for inp, msg in san.items():
            if inp not in seen:
                seen.add(inp)
                cex.append({"category": "sanitizer", "input": inp, "expected": ref.solve(inp),
                            "got": "(sanitizer diagnostic)", "note": msg,
                            "why": explain_failure(ref, inp, ref.solve(inp), "", msg)})
        if fp["suspected_infinite_loop"]:
            s = ref.SAMPLE_INPUT
            cex.append({"category": "smoke run", "input": s, "expected": ref.solve(s), "got": "(timeout)",
                        "note": "", "why": explain_failure(ref, s, ref.solve(s), "(timeout)", "")})
        cex.sort(key=lambda c: (len(c["input"]), c["input"]))

        rep_cfg = rules.get("report", {})
        ul_file = rep_cfg.get("usefulness_limitations_file")
        ul_path = root / ul_file if ul_file else None
        report = {
            "submission": src_path.name,
            "rules_hash": rules_hash,
            "grade": round(total, 2),
            "partial": any(m["status"] == "skipped_first_pass" for m in metrics_out),
            "first_pass": fp,
            "metrics": metrics_out,
            "flags": sorted(set(flags)),
            "counterexamples": cex[:25],
            "suggestions": suggestions,
            "llm": {"enabled": llm_ok, "model": llm.model, "status": llm_msg},
            "llm_summary": None,
            "usefulness_limitations": json.loads(ul_path.read_text()) if ul_path and ul_path.exists() else None,
            "tool_versions": tool_versions(),
            "agent_log": [],
        }
        if rep_cfg.get("llm_summary") and llm_ok:
            step("summary", "asking the local model for a tutor summary")
            report["llm_summary"] = _llm_summary(ctx, report)

    step("collate", f"grade {report['grade']:.2f}/100" + (" (partial)" if report["partial"] else ""))
    out_dir.mkdir(parents=True, exist_ok=True)
    max_ce = rep_cfg.get("max_counterexamples", 5)
    step("write", f"{src_path.stem}.json and {src_path.stem}.txt")
    report["agent_log"] = log
    write_json(out_dir / f"{src_path.stem}.json", report)
    (out_dir / f"{src_path.stem}.txt").write_text(render_text(report, max_ce), encoding="utf-8")
    report["rule_warnings"] = rule_warnings  # for the UI only; not written to disk
    return report


def main():
    ap = argparse.ArgumentParser(description="AutoGrader: rule-driven C program evaluator")
    ap.add_argument("submissions", nargs="+")
    ap.add_argument("--rules", default=str(ROOT / "rules.json"))
    ap.add_argument("--out", default=str(ROOT / "reports"))
    ap.add_argument("--no-llm", action="store_true", help="do not use Ollama (heuristic readability only)")
    ap.add_argument("-v", "--verbose", action="store_true", help="print the agent's steps")
    a = ap.parse_args()
    try:
        for s in a.submissions:
            r = grade(s, a.rules, a.out, use_llm=not a.no_llm,
                      progress=(lambda e: print("   ", e["stage"], "|", e["message"])) if a.verbose else None)
            print(f"{r['submission']:<22} grade {r['grade']:>6.2f}"
                  f"{'  PARTIAL' if r['partial'] else ''}"
                  f"{'  FLAGS: ' + ', '.join(r['flags']) if r['flags'] else ''}")
    except RulesError as e:
        print("rules error:\n  - " + "\n  - ".join(e.errors), file=sys.stderr)
        sys.exit(2)
    except EnvironmentError as e:
        print(f"environment error: {e}", file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()
