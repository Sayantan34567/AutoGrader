"""Standalone tests for analyzers/memory_safety.py"""
import testkit


def test_clean_program():
    r = testkit.run_analyzer("memory_safety", "add_good.c")
    assert r["score"] == 1.0 and r["evidence"]["findings"] == {}


def test_leak_is_found_with_triggering_input():
    r = testkit.run_analyzer("memory_safety", "add_leak.c")
    assert "LeakSanitizer: memory leak" in r["evidence"]["findings"] and r["score"] < 1.0


def test_signed_overflow_reported_by_ubsan():
    r = testkit.run_analyzer("memory_safety", "add.c")
    f = r["evidence"]["findings"]["UBSan: signed integer overflow"]
    assert f["input"].strip() in ("2147483647 1", "2147483647 2147483647") or "2147483647" in f["input"]


def test_null_dereference_is_reported():
    r = testkit.run_analyzer("memory_safety", "add_crash.c")
    assert any("SEGV" in k or "null" in k for k in r["evidence"]["findings"])


def test_report_has_no_pids_or_absolute_paths():
    text = str(testkit.run_analyzer("memory_safety", "add_leak.c")["evidence"])
    assert "==" not in text and "/home/" not in text and "/tmp/" not in text


if __name__ == "__main__":
    testkit.main(globals())
