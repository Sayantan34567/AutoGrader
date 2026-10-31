"""Logical / edge cases: the agent writes its own tests and checks the student against the reference.

Three sources of inputs, all judged against the trusted reference solution (never against the LLM):
  1. the reference module's corner-case library (zero, negatives, boundaries, overflow, whitespace);
  2. seeded random fuzzing (fixed seed -> same inputs on every run);
  3. extra tricky inputs proposed by the local LLM (Ollama), kept only if the reference accepts
     them as valid. They are cached per problem, so every student gets the same ones.
"""
import random

from . import _common as C

NEEDS_EXECUTION = True
PARAMS = {
    "cases": {"type": list, "items": str, "default": []},   # [] = every category the reference has
    "fuzz": {"type": int, "default": 25, "min": 0, "max": 500},
    "seed": {"type": int, "default": 1234},
    "llm_cases": {"type": int, "default": 0, "min": 0, "max": 20},
    "llm_cases_count_in_score": {"type": bool, "default": False},
}

SYSTEM = ("You are a meticulous QA engineer. Given a programming problem, propose test INPUTS "
          "(exact stdin text) that are most likely to break a typical student solution: boundary "
          "values, overflow, odd whitespace, missing trailing newline. Do NOT give expected outputs. "
          'Reply with JSON only: {"cases": [{"input": "<stdin text, use \\n for newlines>", '
          '"why": "<short reason>"}]}')


def llm_inputs(ctx, n, known):
    """Ask Ollama for n extra inputs; returns (cases, info)."""
    info = {"requested": n, "proposed": 0, "valid": 0, "status": "ok"}
    if not ctx.llm.available():
        info["status"] = "skipped: " + ctx.llm.status()[1]
        return [], info
    res = ctx.llm.chat_json(SYSTEM, f"Problem:\n{ctx.statement}\n\nPropose {n} test inputs.")
    if not res["ok"]:
        info["status"] = "skipped: " + str(res["error"])
        return [], info
    out, seen = [], set(known)
    raw = res["data"].get("cases", [])
    raw = raw if isinstance(raw, list) else []
    info["proposed"] = len(raw)
    for item in raw:
        inp = item.get("input") if isinstance(item, dict) else None
        if not isinstance(inp, str) or inp in seen:
            continue
        try:
            ok = ctx.ref.valid_input(inp)
        except Exception:
            ok = False
        if ok:
            seen.add(inp)
            out.append((f"llm: {str(item.get('why', 'LLM-proposed'))[:60]}", inp))
        if len(out) >= n:
            break
    info["valid"] = len(out)
    return out, info


def analyze(ctx, params):
    library = ctx.ref.corner_cases()
    wanted = params["cases"] or list(library)
    unknown = [c for c in wanted if c not in library]
    cases = [(name, inp) for name in wanted for inp in library.get(name, [])]
    rng = random.Random(params["seed"])  # fixed seed -> reproducible fuzz
    cases += [("fuzz", ctx.ref.fuzz_input(rng)) for _ in range(params["fuzz"])]

    extra, llm_info = [], None
    if params["llm_cases"]:
        extra, llm_info = llm_inputs(ctx, params["llm_cases"], {inp for _, inp in cases})

    passed, failing = C.evaluate_inputs(ctx, cases)
    total = len(cases)
    x_passed, x_failing = (C.evaluate_inputs(ctx, extra) if extra else (0, []))
    if params["llm_cases_count_in_score"]:
        score = (passed + x_passed) / (total + len(extra)) if total + len(extra) else None
    else:
        score = passed / total if total else None

    by_cat = {}
    for f in failing + x_failing:
        key = "llm" if f["category"].startswith("llm") else f["category"]
        by_cat[key] = by_cat.get(key, 0) + 1
    fb = f"{passed}/{total} edge cases pass."
    if extra:
        fb += f" LLM-proposed extra inputs: {x_passed}/{len(extra)} pass."
    if by_cat:
        fb += " Failing: " + ", ".join(f"{k} x{v}" for k, v in sorted(by_cat.items())) + "."
    if unknown:
        fb += f" (unknown case categories ignored: {unknown})"
    return {"score": score,
            "evidence": {"cases_run": total, "passed": passed, "failing_by_category": by_cat,
                         "llm_cases": llm_info, "llm_cases_run": len(extra),
                         "llm_cases_passed": x_passed, "unknown_categories": unknown,
                         "failing": failing + x_failing},
            "feedback": fb}
