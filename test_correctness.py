"""Standalone tests for analyzers/correctness.py"""
import testkit


def test_good_solution_passes_everything():
    assert testkit.run_analyzer("correctness", "add_good.c")["score"] == 1.0


def test_overflow_is_reported_with_input_and_expected_output():
    r = testkit.run_analyzer("correctness", "add.c")
    assert r["score"] < 1.0
    f = next(x for x in r["evidence"]["failing"] if x["input"] == "2147483647 1\n")
    assert f["expected"] == "2147483648\n"          # mathematical sum, not the UB value


def test_crash_scores_zero_and_is_described():
    r = testkit.run_analyzer("correctness", "add_crash.c")
    assert r["score"] == 0.0
    assert r["evidence"]["failing"][0]["got"] == "(crashed: SIGSEGV)"


def test_exact_mode_is_stricter(tmp_path):
    src = tmp_path / "t.c"   # prints a trailing space: fine when ignoring trailing whitespace, wrong when exact
    src.write_text('#include <stdio.h>\nint main(void){long long a,b;scanf("%lld %lld",&a,&b);printf("%lld \\n",a+b);return 0;}\n')
    assert testkit.run_analyzer("correctness", src)["score"] == 1.0
    assert testkit.run_analyzer("correctness", src, compare="exact")["score"] == 0.0


if __name__ == "__main__":
    testkit.main(globals())
