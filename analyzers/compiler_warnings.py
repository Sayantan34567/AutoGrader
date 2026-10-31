"""Syntax / warnings: counts gcc diagnostics under the flags given in rules.json."""
import os
import re
import tempfile

from sandbox import compile_c

NEEDS_EXECUTION = False
PARAMS = {
    "flags": {"type": str, "default": "-Wall -Wextra -std=c11"},
    "penalty_per_diagnostic": {"type": float, "default": 0.25, "min": 0, "max": 1},
}


def _compile_only(ctx, flags):
    fd, tmp = tempfile.mkstemp(suffix=".o")
    os.close(fd)
    try:
        return compile_c(ctx.src, tmp, flags + " -c")
    finally:
        os.unlink(tmp)


def analyze(ctx, params):
    flags = params["flags"]
    res = _compile_only(ctx, flags)
    diags = [ln.strip() for ln in res["stderr"].splitlines()
             if re.search(r":\d+:\d+: (warning|error|fatal error):", ln)]
    score = max(0.0, 1.0 - params["penalty_per_diagnostic"] * len(diags))
    hard_error = False
    if not res["ok"]:
        # With -Werror a mere warning also fails the build; only a failure that persists
        # without -Werror is a genuine compile error (zero credit).
        relaxed = _compile_only(ctx, flags.replace("-Werror", ""))
        hard_error = not relaxed["ok"]
        if hard_error or not diags:
            score = 0.0
    clean_diags = [re.sub(r"^.*?:(\d+:\d+:)", r"line \1", d) for d in diags]
    fb = "No diagnostics." if not clean_diags else \
        f"{len(clean_diags)} diagnostic(s): " + "; ".join(d[:90] for d in clean_diags[:3])
    return {"score": score,
            "evidence": {"flags": flags, "compiled": res["ok"], "compile_error": hard_error,
                         "diagnostics": clean_diags[:20]},
            "feedback": fb,
            "suggestions": [f"Fix the compiler diagnostics (build with: gcc {flags})."] if diags else []}
