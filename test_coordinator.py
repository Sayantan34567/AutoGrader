"""End-to-end tests for coordinator.py (the main agent). Ollama is disabled unless a test says otherwise."""
import json
import shutil
import tempfile
from pathlib import Path

import testkit
import coordinator
from analyzers import REGISTRY


def g(name, out, use_llm=False, rules=None):
    return coordinator.grade(testkit.SAMPLES / name, rules or testkit.RULES_PATH, out, use_llm=use_llm)


def metric(rep, name):
    return next(m for m in rep["metrics"] if m["name"] == name)


def test_good_submission_near_perfect(tmp_path):
    rep = g("add_good.c", tmp_path)
    assert rep["grade"] > 99 and not rep["partial"] and rep["flags"] == ["readability_used_heuristic_fallback"]
    assert (tmp_path / "add_good.json").exists() and (tmp_path / "add_good.txt").exists()


def test_overflow_counterexample_has_input_expected_and_explanation(tmp_path):
    rep = g("add.c", tmp_path)
    c = next(c for c in rep["counterexamples"] if c["input"] == "2147483647 1\n")
    assert c["expected"] == "2147483648\n" and "overflow" in c["why"]
    assert "INPUT:" in (tmp_path / "add.txt").read_text() and "EXPECTED:" in (tmp_path / "add.txt").read_text()


def test_infinite_loop_gives_partial_report(tmp_path):
    rep = g("add_infinite.c", tmp_path)
    assert rep["partial"] and "suspected_infinite_loop" in rep["flags"]
    assert metric(rep, "correctness")["status"] == "skipped_first_pass"
    assert metric(rep, "syntax")["status"] == "ok" and metric(rep, "originality")["status"] == "ok"
    assert any(c["got"] == "(timeout)" for c in rep["counterexamples"])


def test_syntax_error_gets_partial_report(tmp_path):
    rep = g("add_syntax_error.c", tmp_path)
    assert rep["partial"] and "compile_failed" in rep["flags"] and rep["first_pass"]["compile_error"]


def test_crash_leak_and_hardcoded(tmp_path):
    assert metric(g("add_crash.c", tmp_path), "correctness")["score"] == 0.0
    leak = g("add_leak.c", tmp_path)
    assert metric(leak, "memory_safety")["score"] < 1.0 and metric(leak, "correctness")["score"] == 1.0
    hard = g("add_hardcoded.c", tmp_path)
    assert metric(hard, "correctness")["score"] == 1.0 and metric(hard, "logical")["score"] < 0.3


def test_copy_is_flagged(tmp_path):
    rep = g("add_copy.c", tmp_path)
    assert any(f.startswith("suspected_copy") for f in rep["flags"])


def test_prompt_injection_is_flagged(tmp_path):
    assert "possible_prompt_injection" in g("add_injection.c", tmp_path)["flags"]


def test_same_submission_same_rules_same_report_bytes(tmp_path):
    g("add.c", tmp_path / "a")
    g("add.c", tmp_path / "b")
    for ext in ("json", "txt"):
        assert (tmp_path / "a" / f"add.{ext}").read_bytes() == (tmp_path / "b" / f"add.{ext}").read_bytes()


def test_same_report_with_llm_after_caching(tmp_path):
    with testkit.FakeOllama() as fo:
        rules = json.loads(testkit.RULES_PATH.read_text())
        rules["llm"].update(host=fo.url, model=fo.model)
        rp = tmp_path / "rules.json"
        rp.write_text(json.dumps(rules))
        cache = testkit.ROOT / ".cache" / "llm"
        shutil.rmtree(cache, ignore_errors=True)
        try:
            a = g("add.c", tmp_path / "a", use_llm=True, rules=rp)
            calls = len(fo.calls)
            b = g("add.c", tmp_path / "b", use_llm=True, rules=rp)
            assert len(fo.calls) == calls                      # second run is served from the cache
            assert a["llm_summary"]["text"] == "Fix overflow first."
            for ext in ("json", "txt"):                     # first run (cache miss) == second run (cache hit)
                assert (tmp_path / "a" / f"add.{ext}").read_bytes() == (tmp_path / "b" / f"add.{ext}").read_bytes()
            assert "readability_used_heuristic_fallback" not in a["flags"]
        finally:
            shutil.rmtree(cache, ignore_errors=True)


def test_crashing_analyzer_is_isolated(tmp_path):
    original = REGISTRY["modularity"]["fn"]
    REGISTRY["modularity"]["fn"] = lambda ctx, p: 1 / 0
    try:
        rep = g("add_good.c", tmp_path)
    finally:
        REGISTRY["modularity"]["fn"] = original
    m = metric(rep, "modularity")
    assert m["status"] == "analyzer_error" and "analyzer_error:modularity" in rep["flags"]
    assert abs(sum(x["effective_weight"] for x in rep["metrics"]) - 1.0) < 1e-3     # weights renormalised


def test_missing_tool_redistributes_weight(tmp_path):
    import analyzers.complexity as cx
    real = cx.shutil.which
    cx.shutil.which = lambda name, *a, **k: None if name == "valgrind" else real(name, *a, **k)
    try:
        rep = g("add_good.c", tmp_path)
    finally:
        cx.shutil.which = real
    assert metric(rep, "complexity")["status"] == "skipped_tool_missing"
    assert rep["grade"] > 99 and abs(sum(x["effective_weight"] for x in rep["metrics"]) - 1.0) < 1e-3


def test_invalid_rules_stop_the_run(tmp_path):
    rules = json.loads(testkit.RULES_PATH.read_text())
    rules["metrics"][0]["weight"] = 0.5
    rp = tmp_path / "bad.json"
    rp.write_text(json.dumps(rules))
    try:
        g("add.c", tmp_path, rules=rp)
        raise AssertionError("expected RulesError")
    except coordinator.RulesError as e:
        assert any("sum to 1.00" in x for x in e.errors)


def test_progress_callback_reports_every_step(tmp_path):
    events = []
    coordinator.grade(testkit.SAMPLES / "add_good.c", testkit.RULES_PATH, tmp_path, use_llm=False, progress=events.append)
    stages = [e["stage"] for e in events]
    assert stages[:3] == ["rules", "llm", "first_pass"] and stages[-1] == "write"
    assert sum(1 for e in events if e["stage"] == "dispatch") == 9


def test_rules_are_the_only_thing_that_changes_the_grade(tmp_path):
    rules = json.loads(testkit.RULES_PATH.read_text())
    for m in rules["metrics"]:
        m["weight"] = 0.0
        if m["name"] == "correctness":
            m["weight"] = 1.0
    rp = tmp_path / "only_correctness.json"
    rp.write_text(json.dumps(rules))
    assert g("add.c", tmp_path, rules=rp)["grade"] == 70.0       # 7 of 10 hidden tests


if __name__ == "__main__":
    testkit.main(globals())
