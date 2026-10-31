"""Modularity: are there helper functions, and does main() actually call them?"""
import cparse

NEEDS_EXECUTION = False
PARAMS = {
    "min_functions": {"type": int, "default": 2, "min": 1},
    "expect_helpers": {"type": bool, "default": True},
}


def analyze(ctx, params):
    funcs = cparse.functions(ctx.source)
    names = [f["name"] for f in funcs]
    helpers = [f for f in funcs if f["name"] != "main"]
    main = next((f for f in funcs if f["name"] == "main"), None)
    used = [h["name"] for h in helpers if main and h["name"] in main["calls"]]
    need = params["min_functions"]
    score = min(1.0, len(funcs) / need)
    if params["expect_helpers"] and helpers and not used:
        score = min(score, 0.7)  # helpers defined but never called from main
    fb = (f"{len(funcs)} function(s): {', '.join(names) or 'none'}." if score >= 1
          else f"Only {len(funcs)} function(s) defined (expected at least {need}).")
    return {"score": score,
            "evidence": {"functions_defined": len(funcs), "expected_min": need,
                         "names": names, "helpers_called_from_main": used},
            "feedback": fb,
            "suggestions": ["Extract the core logic into a helper, e.g. `long long add(long long a, "
                            "long long b)`, and call it from main."] if score < 1 else []}
