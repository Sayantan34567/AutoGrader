"""Correctness: runs the instructor's hidden I/O tests (tests_dir/NN.in + NN.out)."""
from . import _common as C

NEEDS_EXECUTION = True
PARAMS = {
    "compare": {"type": str, "default": "ignore_trailing_whitespace",
                "choices": ["ignore_trailing_whitespace", "exact"]},
}


def load_tests(d):
    out = []
    for inp in sorted(d.glob("*.in")):
        exp = inp.with_suffix(".out")
        if exp.exists():
            out.append((inp.stem, inp.read_text(), exp.read_text()))
    return out


def analyze(ctx, params):
    tests = load_tests(ctx.tests_dir)
    if not tests:
        return {"score": None, "evidence": {"error": f"no tests in {ctx.tests_dir}"},
                "feedback": "No hidden tests found; metric skipped."}
    passed, failing = 0, []
    for name, inp, exp in tests:
        res = C.run_case(ctx, inp)
        if res["status"] == "ok" and C.norm(res["stdout"], params["compare"]) == C.norm(exp, params["compare"]):
            passed += 1
        else:
            failing.append({"category": f"test {name}", "input": inp, "expected": exp,
                            "got": C.describe(res) if res["status"] != "ok" else res["stdout"],
                            "note": C.first_line(res["stderr"])})
    total = len(tests)
    fb = f"{passed}/{total} tests pass."
    if failing:
        fb += f" First failure: input {failing[0]['input'].strip()!r}."
    return {"score": passed / total,
            "evidence": {"tests_passed": passed, "tests_total": total, "failing": failing},
            "feedback": fb}
