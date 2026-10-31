"""Memory safety: rebuilds with AddressSanitizer + UBSan and runs the sample, hidden-test and corner
inputs; adds a valgrind leak check. Reports leaks, overflows and undefined behaviour with the input
that triggers each."""
import re
import shutil

from sandbox import compile_c, run_cmd

from . import _common as C

NEEDS_EXECUTION = True
PARAMS = {
    "flags": {"type": str, "default": "-fsanitize=address,undefined"},
    "valgrind": {"type": bool, "default": True},
}

_UB = re.compile(r"runtime error: (.+)")
_ASAN = re.compile(r"ERROR: AddressSanitizer: ([\w-]+)")


def _inputs(ctx):
    ins = [("sample", ctx.ref.SAMPLE_INPUT)]
    d = ctx.tests_dir
    if d.exists():
        ins += [(f"test {f.stem}", f.read_text()) for f in sorted(d.glob("*.in"))]
    for cat, lst in ctx.ref.corner_cases().items():
        ins += [(cat, inp) for inp in lst]
    return ins


def analyze(ctx, params):
    flags = params["flags"]
    exe = ctx.workdir / "san_bin"
    c = compile_c(ctx.src, exe, f"-O1 -g -fno-omit-frame-pointer {flags}")
    if not c["ok"]:
        return {"score": None, "evidence": {"error": c["stderr"][:300]},
                "feedback": "Sanitizer build failed (sudo apt install libasan8 libubsan1?); metric skipped."}
    env = {"ASAN_OPTIONS": "detect_leaks=1:abort_on_error=0", "UBSAN_OPTIONS": "print_stacktrace=0"}
    findings = {}  # kind -> first example that triggers it
    for cat, inp in _inputs(ctx):
        res = C.run_case(ctx, inp, binary=exe, use_as=False, env=env)
        err = res["stderr"]
        kinds = ["UBSan: " + m.group(1).split(":")[0].strip() for m in _UB.finditer(err)]
        kinds += ["ASan: " + m.group(1) for m in _ASAN.finditer(err)]
        if "LeakSanitizer: detected memory leaks" in err:
            kinds.append("LeakSanitizer: memory leak")
        for k in kinds:
            if k not in findings:
                line = next((ln for ln in err.splitlines() if "runtime error" in ln or "ERROR:" in ln), "")
                findings[k] = {"input": inp, "category": cat, "message": C.clean(line)}
    valgrind = None
    if params["valgrind"] and shutil.which("valgrind"):
        vexe = ctx.workdir / "vg_bin"
        if compile_c(ctx.src, vexe, "-O0 -g")["ok"]:
            r = run_cmd(["valgrind", "--leak-check=full", str(vexe)], ctx.ref.SAMPLE_INPUT,
                        timeout_s=30, use_as=False)
            m = re.search(r"definitely lost: ([\d,]+) bytes", r["stderr"])
            lost = int(m.group(1).replace(",", "")) if m else 0
            valgrind = {"definitely_lost_bytes": lost}
            if lost and "LeakSanitizer: memory leak" not in findings:
                findings["valgrind: definite leak"] = {"input": ctx.ref.SAMPLE_INPUT, "category": "sample",
                                                       "message": f"{lost} bytes definitely lost"}
    score = max(0.0, 1.0 - 0.34 * len(findings))
    fb = "ASan/UBSan clean." if not findings else "; ".join(
        f"{k} (input {v['input'].strip()!r})" for k, v in findings.items())
    return {"score": score,
            "evidence": {"flags": flags, "findings": findings, "valgrind": valgrind or "skipped"},
            "feedback": fb,
            "suggestions": [f"Fix the sanitizer findings; recompile with {flags} to reproduce."] if findings else []}
