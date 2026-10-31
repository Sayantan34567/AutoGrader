"""Time efficiency: counts CPU instructions (valgrind/callgrind) at growing input sizes and fits
O(1) .. O(n^3). Instruction counts are deterministic; wall-clock time is not, and the grade must be
reproducible."""
import math
import random
import re
import shutil

from sandbox import compile_c, run_cmd

NEEDS_EXECUTION = True
PARAMS = {
    "required": {"type": str, "default": "O(1)",
                 "choices": ["O(1)", "O(log n)", "O(n)", "O(n log n)", "O(n^2)", "O(n^3)"]},
    "sizes": {"type": list, "items": int, "default": [1, 10, 100]},
    "valgrind_timeout_s": {"type": int, "default": 60, "min": 1},
}

MODELS = [
    ("O(1)", lambda n: 1.0),
    ("O(log n)", lambda n: math.log2(n + 1)),
    ("O(n)", lambda n: float(n)),
    ("O(n log n)", lambda n: n * math.log2(n + 1)),
    ("O(n^2)", lambda n: float(n * n)),
    ("O(n^3)", lambda n: float(n ** 3)),
]
RANK = {name: i for i, (name, _) in enumerate(MODELS)}


def _fit(sizes, ys, f):
    """Least squares y = a + b*f(n) with b >= 0; returns the relative RMS error."""
    xs = [f(n) for n in sizes]
    k = len(xs)
    mx, my = sum(xs) / k, sum(ys) / k
    var = sum((x - mx) ** 2 for x in xs)
    b = 0.0 if var == 0 else max(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var, 0.0)
    a = my - b * mx
    if var == 0:
        a, b = my, 0.0
    return math.sqrt(sum(((y - (a + b * x)) / y) ** 2 for x, y in zip(xs, ys)) / k)


def classify(sizes, ys, tol=0.05):
    for name, f in MODELS:
        if len(set(sizes)) < 2 and name != "O(1)":
            continue
        if _fit(sizes, ys, f) < tol:
            return name
    return "unclassified"


def _count_ir(exe, inp, timeout):
    r = run_cmd(["valgrind", "--tool=callgrind", "--callgrind-out-file=/dev/null", str(exe)],
                inp, timeout_s=timeout, use_as=False)
    m = re.search(r"Collected : (\d+)", r["stderr"])
    return (int(m.group(1)) if m and r["status"] == "ok" else None), r


def analyze(ctx, params):
    if not shutil.which("valgrind"):
        return {"score": None, "evidence": {"error": "valgrind not installed"},
                "feedback": "valgrind missing (sudo apt install valgrind); complexity metric skipped."}
    required, sizes = params["required"], params["sizes"]
    exe = ctx.workdir / "cx_bin"
    if not compile_c(ctx.src, exe, "-O0 -g")["ok"]:
        return {"score": 0.0, "evidence": {}, "feedback": "Could not build for profiling."}
    rng = random.Random(7)
    inputs = [ctx.ref.gen_input(n, rng) for n in sizes]
    irs = []
    for n, inp in zip(sizes, inputs):
        ir, r = _count_ir(exe, inp, params["valgrind_timeout_s"])
        if ir is None:
            return {"score": 0.0, "evidence": {"failed_size": n, "status": r["status"]},
                    "feedback": f"Program failed or timed out at size {n} while profiling."}
        irs.append(ir)
    est = classify(sizes, irs)
    if est == "unclassified":
        score, fb = 0.0, f"Growth matches no model up to O(n^3); instruction counts {irs}."
    else:
        d = RANK[est] - RANK[required]
        score = 1.0 if d <= 0 else (0.5 if d == 1 else 0.0)
        fb = f"Estimated {est} (required {required})."
    note = ""
    if len(set(inputs)) == 1:
        note = "This problem has no size parameter (every size gives the same input), so only O(1) can be shown."
    return {"score": score,
            "evidence": {"required": required, "estimated": est, "sizes": sizes,
                         "instruction_counts": irs, "note": note},
            "feedback": fb}
