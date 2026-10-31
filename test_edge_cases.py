"""Standalone tests for analyzers/edge_cases.py (includes the Ollama-proposed extra inputs)"""
import testkit


def test_good_solution_passes_all_edge_cases():
    assert testkit.run_analyzer("edge_cases", "add_good.c", llm_cases=0)["score"] == 1.0


def test_hardcoded_solution_is_caught_by_fuzz_even_though_visible_tests_pass():
    assert testkit.run_analyzer("correctness", "add_hardcoded.c")["score"] == 1.0
    r = testkit.run_analyzer("edge_cases", "add_hardcoded.c", llm_cases=0)
    assert r["score"] < 0.3 and r["evidence"]["failing_by_category"].get("fuzz", 0) > 0


def test_overflow_category_fails_for_int_solution():
    r = testkit.run_analyzer("edge_cases", "add.c", llm_cases=0)
    assert r["evidence"]["failing_by_category"].get("int_overflow") == 3


def test_fuzz_is_reproducible():
    a = testkit.run_analyzer("edge_cases", "add.c", llm_cases=0)
    b = testkit.run_analyzer("edge_cases", "add.c", llm_cases=0)
    assert a == b


def test_llm_cases_are_validated_by_the_reference_and_kept_out_of_the_score_by_default():
    with testkit.FakeOllama() as fo:
        r = testkit.run_analyzer("edge_cases", "add.c", llm_cfg=fo.cfg(), llm_cases=6)
        base = testkit.run_analyzer("edge_cases", "add.c", llm_cases=0)
    info = r["evidence"]["llm_cases"]
    assert info["proposed"] == 5 and info["valid"] == 2          # duplicate + 2 invalid inputs dropped
    assert r["score"] == base["score"]                            # not counted in the score
    assert r["evidence"]["llm_cases_run"] == 2


def test_llm_failures_can_count_in_the_score():
    extra = [{"input": "2000000000 2000000000\n", "why": "sum overflows"}]
    with testkit.FakeOllama(extra_cases=extra) as fo:
        r = testkit.run_analyzer("edge_cases", "add.c", llm_cfg=fo.cfg(), llm_cases=3,
                                 llm_cases_count_in_score=True)
    assert r["evidence"]["llm_cases_passed"] == 0
    assert any(f["category"].startswith("llm") for f in r["evidence"]["failing"])


def test_works_without_ollama():
    r = testkit.run_analyzer("edge_cases", "add_good.c", llm_cfg={"enabled": False}, llm_cases=6)
    assert r["score"] == 1.0 and r["evidence"]["llm_cases"]["status"].startswith("skipped")


if __name__ == "__main__":
    testkit.main(globals())
