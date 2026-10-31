"""Helpers shared by the execution-based analyzers (not an analyzer itself)."""
import re

from sandbox import run_binary


def norm(text, mode="ignore_trailing_whitespace"):
    if mode == "exact":
        return text
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def run_case(ctx, inp, binary=None, **kw):
    return run_binary(binary or ctx.binary, inp, ctx.time_limit, ctx.mem_mb, **kw)


def describe(res):
    if res["status"] == "timeout":
        return "(timeout)"
    if res["status"] == "crash":
        return f"(crashed: {res['signal']})"
    if res["status"] == "nonzero_exit":
        return f"(exit code {res['rc']})"
    if res["status"] == "error":
        return "(could not run)"
    return res["stdout"]


def clean(text, n=200):
    """Make diagnostics deterministic: no absolute paths, no PIDs."""
    text = re.sub(r"/[^\s:]*/([\w.\-]+\.c)", r"\1", text)
    text = re.sub(r"^==\d+==", "", text.strip())
    return text[:n]


def first_line(text):
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    return clean(lines[0]) if lines else ""


def evaluate_inputs(ctx, cases, compare="ignore_trailing_whitespace"):
    """cases: list of (category, input). Returns (passed, failing list)."""
    passed, failing = 0, []
    for cat, inp in cases:
        expected = ctx.ref.solve(inp)
        res = run_case(ctx, inp)
        if res["status"] == "ok" and norm(res["stdout"], compare) == norm(expected, compare):
            passed += 1
        else:
            failing.append({"category": cat, "input": inp, "expected": expected,
                            "got": describe(res) if res["status"] != "ok" else res["stdout"],
                            "note": first_line(res["stderr"])})
    return passed, failing
