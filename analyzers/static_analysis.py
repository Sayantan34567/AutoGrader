"""Structure: cyclomatic complexity and function length (lizard) plus cppcheck findings."""
import shutil
import subprocess

import cparse

NEEDS_EXECUTION = False
PARAMS = {
    "max_cyclomatic": {"type": int, "default": 10, "min": 1},
    "max_function_length": {"type": int, "default": 50, "min": 1},
}


def _functions(source, path):
    try:
        import lizard  # optional: pip install lizard
        info = lizard.analyze_file(str(path))
        return [{"name": f.name, "cyclomatic": f.cyclomatic_complexity,
                 "length": f.end_line - f.start_line + 1} for f in info.function_list], "lizard"
    except Exception:
        return [{"name": f["name"], "cyclomatic": f["cyclomatic"], "length": f["length"]}
                for f in cparse.functions(source)], "builtin"


def _cppcheck(path):
    if not shutil.which("cppcheck"):
        return None
    try:
        p = subprocess.run(["cppcheck", "--enable=warning,style,performance,portability", "--quiet",
                            "--template={line}:{severity}:{id}:{message}", str(path)],
                           capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return None
    return [ln for ln in p.stderr.splitlines() if ln.strip()]


def analyze(ctx, params):
    funcs, engine = _functions(ctx.source, ctx.src)
    bad = [f for f in funcs if f["cyclomatic"] > params["max_cyclomatic"]
           or f["length"] > params["max_function_length"]]
    issues = _cppcheck(ctx.src)
    score = 1.0 - 0.25 * len(bad)
    if issues:
        score -= min(0.3, 0.05 * len(issues))
    msgs = [f"{f['name']}(): cyclomatic {f['cyclomatic']} (max {params['max_cyclomatic']}), "
            f"length {f['length']} (max {params['max_function_length']})" for f in bad]
    fb = "Complexity and length within limits." if not bad else "; ".join(msgs)
    if issues:
        fb += f" cppcheck: {len(issues)} issue(s): {issues[0][:80]}"
    return {"score": max(0.0, score),
            "evidence": {"engine": engine, "functions": funcs, "violations": msgs,
                         "cppcheck": issues if issues is not None else "not installed"},
            "feedback": fb,
            "suggestions": ["Split long or branchy functions into smaller helpers."] if bad else []}
