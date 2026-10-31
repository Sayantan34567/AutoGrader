"""Standalone tests for analyzers/compiler_warnings.py"""
import testkit


def test_clean_file_gets_full_marks():
    r = testkit.run_analyzer("compiler_warnings", "add_good.c")
    assert r["score"] == 1.0 and r["evidence"]["diagnostics"] == []


def test_syntax_error_gets_zero():
    r = testkit.run_analyzer("compiler_warnings", "add_syntax_error.c")
    assert r["score"] == 0.0 and r["evidence"]["compile_error"] is True


def test_warning_under_werror_is_partial_credit_not_zero(tmp_path):
    src = tmp_path / "w.c"
    src.write_text("#include <stdio.h>\nint main(void) { int unused; printf(\"hi\\n\"); return 0; }\n")
    r = testkit.run_analyzer("compiler_warnings", src)
    assert 0.0 < r["score"] < 1.0 and r["evidence"]["compile_error"] is False


if __name__ == "__main__":
    testkit.main(globals())
