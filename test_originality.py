"""Standalone tests for analyzers/originality.py"""

import testkit


def test_renamed_copy_is_flagged_for_human_review():
    r = testkit.run_analyzer("originality", "add_copy.c")

    assert r["score"] == 1.0
    assert any(
        f.startswith("suspected_copy")
        and "human review required" in f
        for f in r["flags"]
    )
    assert r["evidence"]["most_similar_to"] == "submissions/other_add.c"


def test_different_program_is_not_flagged():
    r = testkit.run_analyzer("originality", "add_good.c")

    assert r["score"] == 1.0
    assert r["flags"] == []


def test_identical_resubmission_is_not_a_copy():
    r = testkit.run_analyzer("originality", "add.c")

    assert "add.c" in r["evidence"]["ignored_identical_resubmission"]
    assert r["flags"] == []


def test_too_short_program_is_not_judged(tmp_path):
    src = tmp_path / "s.c"
    src.write_text("int main(void) { return 0; }\n")

    r = testkit.run_analyzer("originality", src)

    assert r["score"] == 1.0
    assert "too short" in r["evidence"]["note"]


def test_llm_reference_solutions_flag_matching_code():
    with testkit.FakeOllama() as fo:
        r = testkit.run_analyzer(
            "originality",
            "add_copy.c",
            llm_cfg=fo.cfg(),
            llm_reference_solutions=2
        )

    assert r["evidence"]["llm_solutions"]["max_similarity"] >= 0.9
    assert any(f.startswith("possible_llm_generated") for f in r["flags"])


def test_llm_style_signals_are_reported(tmp_path):
    src = tmp_path / "llm.c"

    src.write_text(
        '#include <stdio.h>\n'
        '// Function to add two numbers\n'
        'long long add(long long a, long long b) {\n'
        '    // Return the sum\n'
        '    return a + b;\n'
        '}\n'
        '// Example usage\n'
        'int main() {\n'
        '    long long a, b;\n'
        '    // Read the two numbers\n'
        '    scanf("%lld %lld", &a, &b);\n'
        '    printf("%lld\\n", add(a, b));\n'
        '    return 0;\n'
        '}\n'
    )

    r = testkit.run_analyzer("originality", src)

    assert len(r["evidence"]["llm_style_signals"]) >= 3
    assert any(f.startswith("possible_llm_style") for f in r["flags"])


def test_known_limitation_independent_minimal_solution_is_flagged_for_review():
    r = testkit.run_analyzer("originality", "add_minimal.c")

    assert r["score"] == 1.0
    assert any(f.startswith("suspected_copy") for f in r["flags"])


if __name__ == "__main__":
    testkit.main(globals())
