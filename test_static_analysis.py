"""Standalone tests for analyzers/static_analysis.py"""
import testkit


def test_small_program_is_within_limits():
    r = testkit.run_analyzer("static_analysis", "add_good.c")
    assert r["score"] == 1.0 and r["evidence"]["violations"] == []


def test_branchy_function_is_flagged(tmp_path):
    body = "\n".join(f"    if (x == {i}) y += {i};" for i in range(12))
    src = tmp_path / "b.c"
    src.write_text(f"int f(int x) {{\n    int y = 0;\n{body}\n    return y;\n}}\nint main(void) {{ return f(1); }}\n")
    r = testkit.run_analyzer("static_analysis", src, max_cyclomatic=8)
    assert r["score"] < 1.0 and "f()" in r["evidence"]["violations"][0]


if __name__ == "__main__":
    testkit.main(globals())
