"""Analyzer registry (auto-discovery).

Adding a metric = drop a file in analyzers/ that defines:

    NEEDS_EXECUTION = False      # True -> skipped when the program does not compile / hangs
    PARAMS = {"my_param": {"type": int, "default": 3, "min": 1}}   # validated by check_rules.py
    def analyze(ctx, params) -> {"score": 0..1 or None, "evidence": {...},
                                 "feedback": "...", "suggestions": [...], "flags": [...]}

and reference it from rules.json ("analyzer": "<file name without .py>").
score=None means "could not run" (e.g. a tool is missing): its weight is redistributed.
"""
import importlib
import pkgutil

REGISTRY = {}

for _m in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
    if _m.name.startswith("_"):
        continue
    _mod = importlib.import_module(f"{__name__}.{_m.name}")
    if hasattr(_mod, "analyze"):
        REGISTRY[_m.name] = {
            "fn": _mod.analyze,
            "needs_execution": getattr(_mod, "NEEDS_EXECUTION", False),
            "params": getattr(_mod, "PARAMS", {}),
            "doc": (_mod.__doc__ or "").strip().splitlines()[0] if _mod.__doc__ else "",
        }
