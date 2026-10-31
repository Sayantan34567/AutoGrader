#!/usr/bin/env python3
"""Validate rules.json before any grading happens.

    python check_rules.py                 # checks ./rules.json
    python check_rules.py other.json --ollama   # also checks the Ollama server and model

Importable: validate_rules(rules, root) -> (errors, warnings); load_rules(path) raises RulesError.
Errors stop the run; warnings (unknown parameter names, empty test folders ...) do not.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from analyzers import REGISTRY

ROOT = Path(__file__).resolve().parent
LLM_KEYS = {"enabled", "host", "model", "temperature", "seed", "timeout_s", "num_predict"}
REPORT_KEYS = {"usefulness_limitations_file", "llm_summary", "max_counterexamples"}


class RulesError(Exception):
    def __init__(self, errors):
        self.errors = errors if isinstance(errors, list) else [errors]
        super().__init__("; ".join(self.errors))


def _is(value, typ):
    if typ is bool:
        return isinstance(value, bool)
    if typ is int:
        return isinstance(value, int) and not isinstance(value, bool)
    if typ is float:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, typ)


def _check_value(label, value, spec, errors):
    typ = spec["type"]
    if not _is(value, typ):
        errors.append(f"{label}: expected {typ.__name__}, got {type(value).__name__} ({value!r})")
        return
    if typ in (int, float):
        if "min" in spec and value < spec["min"]:
            errors.append(f"{label}: {value} is below the minimum {spec['min']}")
        if "max" in spec and value > spec["max"]:
            errors.append(f"{label}: {value} is above the maximum {spec['max']}")
    if "choices" in spec and value not in spec["choices"]:
        errors.append(f"{label}: {value!r} must be one of {spec['choices']}")
    if typ is list and "items" in spec:
        for i, item in enumerate(value):
            if not _is(item, spec["items"]):
                errors.append(f"{label}[{i}]: expected {spec['items'].__name__}, got {item!r}")


def with_defaults(spec, params):
    """Merge a metric's params over the analyzer's declared defaults."""
    merged = {k: s["default"] for k, s in spec.items() if "default" in s}
    merged.update(params or {})
    return merged


def validate_rules(rules, root=ROOT):
    root = Path(root)
    errors, warnings = [], []
    if not isinstance(rules, dict):
        return ["rules file must contain a JSON object"], warnings

    prob = rules.get("problem")
    if not isinstance(prob, dict):
        errors.append("'problem' must be an object with id, statement, reference, tests_dir")
        prob = {}
    for k in ("id", "statement", "reference"):
        if not isinstance(prob.get(k), str) or not prob.get(k, "").strip():
            errors.append(f"problem.{k} is required (non-empty string)")
    ref = prob.get("reference")
    if isinstance(ref, str) and not (root / ref).is_file():
        errors.append(f"problem.reference: file not found: {ref}")

    for key, lo in (("time_limit_s", 0), ("memory_limit_mb", 0)):
        v = rules.get(key)
        if not _is(v, float) or v <= lo:
            errors.append(f"'{key}' is required and must be a number > 0")

    llm = rules.get("llm", {})
    if not isinstance(llm, dict):
        errors.append("'llm' must be an object")
    else:
        for k in llm:
            if k not in LLM_KEYS:
                warnings.append(f"llm.{k}: unknown key (known: {sorted(LLM_KEYS)})")
        if "model" in llm and not (isinstance(llm["model"], str) and llm["model"].strip()):
            errors.append("llm.model must be a non-empty string, e.g. 'llama3.2:3b'")
        if "host" in llm and not (isinstance(llm["host"], str) and llm["host"].startswith("http")):
            errors.append("llm.host must be a URL such as http://localhost:11434")
        if "temperature" in llm and not (_is(llm["temperature"], float) and 0 <= llm["temperature"] <= 2):
            errors.append("llm.temperature must be a number between 0 and 2 (use 0 for reproducibility)")
        elif llm.get("temperature", 0) != 0:
            warnings.append("llm.temperature != 0 weakens reproducibility (answers are cached, but "
                            "different machines will see different first answers)")
        if "seed" in llm and not _is(llm["seed"], int):
            errors.append("llm.seed must be an integer")

    rep = rules.get("report", {})
    if isinstance(rep, dict):
        for k in rep:
            if k not in REPORT_KEYS:
                warnings.append(f"report.{k}: unknown key")
        f = rep.get("usefulness_limitations_file")
        if f and not (root / f).is_file():
            warnings.append(f"report.usefulness_limitations_file not found: {f}")
    else:
        errors.append("'report' must be an object")

    metrics = rules.get("metrics")
    if not isinstance(metrics, list) or not metrics:
        errors.append("'metrics' must be a non-empty list")
        return errors, warnings

    names, total, tests_needed = set(), 0.0, False
    for i, m in enumerate(metrics):
        where = f"metrics[{i}]"
        if not isinstance(m, dict):
            errors.append(f"{where}: must be an object")
            continue
        an = m.get("analyzer")
        if an not in REGISTRY:
            errors.append(f"{where}: unknown analyzer {an!r}. Available: {sorted(REGISTRY)}")
            continue
        name = m.get("name", an)
        where = f"metric '{name}'"
        if name in names:
            errors.append(f"{where}: duplicate metric name")
        names.add(name)
        w = m.get("weight")
        if not _is(w, float) or not 0 <= w <= 1:
            errors.append(f"{where}: weight must be a number between 0 and 1 (got {w!r})")
            continue
        if m.get("enabled", True) is not False:
            total += w
        if an == "correctness" and m.get("enabled", True):
            tests_needed = True
        params = m.get("params", {})
        if not isinstance(params, dict):
            errors.append(f"{where}: params must be an object")
            continue
        spec = REGISTRY[an]["params"]
        for k, v in params.items():
            if k not in spec:
                warnings.append(f"{where}: unknown param '{k}' for analyzer '{an}' "
                                f"(known: {sorted(spec)})")
            else:
                _check_value(f"{where}.params.{k}", v, spec[k], errors)

    if abs(total - 1.0) > 1e-6:
        errors.append(f"weights of enabled metrics must sum to 1.00 (they sum to {total:.4f})")

    td = prob.get("tests_dir")
    if tests_needed:
        if not isinstance(td, str) or not (root / td).is_dir():
            errors.append(f"problem.tests_dir: folder not found: {td!r} (needed by the correctness metric)")
        elif not list((root / td).glob("*.in")):
            warnings.append(f"problem.tests_dir {td}: no *.in / *.out test pairs found")
    return errors, warnings


def rules_hash(rules):
    canonical = json.dumps(rules, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def load_rules(path, root=ROOT):
    """Read + validate. Returns (rules, rules_hash, warnings). Raises RulesError."""
    path = Path(path)
    try:
        rules = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise RulesError(f"rules file not found: {path}")
    except json.JSONDecodeError as e:
        raise RulesError(f"{path.name} is not valid JSON: {e}")
    errors, warnings = validate_rules(rules, root)
    if errors:
        raise RulesError(errors)
    return rules, rules_hash(rules), warnings


def main():
    ap = argparse.ArgumentParser(description="Validate an AutoGrader rules file")
    ap.add_argument("rules", nargs="?", default=str(ROOT / "rules.json"))
    ap.add_argument("--ollama", action="store_true", help="also check the Ollama server and model")
    a = ap.parse_args()
    try:
        rules, h, warnings = load_rules(a.rules)
    except RulesError as e:
        for err in e.errors:
            print(f"ERROR   {err}")
        sys.exit(1)
    for w in warnings:
        print(f"WARNING {w}")
    enabled = [m for m in rules["metrics"] if m.get("enabled", True)]
    print(f"OK  {a.rules}: {len(enabled)} metrics, weights sum to 1.00, {h[:19]}...")
    if a.ollama:
        from llm import OllamaClient
        ok, msg = OllamaClient(rules.get("llm")).status(refresh=True)
        print(("OK  " if ok else "WARN ") + msg)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
