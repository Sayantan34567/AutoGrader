"""Standalone tests for analyzers/modularity.py"""
import testkit


def test_helper_function_present():
    r = testkit.run_analyzer("modularity", "add_good.c")
    assert r["score"] == 1.0 and "add" in r["evidence"]["helpers_called_from_main"]


def test_only_main_gets_half_marks():
    r = testkit.run_analyzer("modularity", "add.c")
    assert r["score"] == 0.5 and r["suggestions"]


def test_unused_helper_is_capped(tmp_path):
    src = tmp_path / "u.c"
    src.write_text("static int add(int a, int b) { return a + b; }\nint main(void) { return 0; }\n")
    assert testkit.run_analyzer("modularity", src)["score"] == 0.7


if __name__ == "__main__":
    testkit.main(globals())
