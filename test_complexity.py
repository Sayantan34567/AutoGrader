"""Standalone tests for analyzers/complexity.py"""
import testkit
from analyzers.complexity import classify


def test_classifier_recognises_growth_rates():
    sizes = [1, 10, 100, 1000]
    assert classify(sizes, [500, 500, 500, 500]) == "O(1)"
    assert classify(sizes, [100 + 7 * n for n in sizes]) == "O(n)"
    assert classify(sizes, [100 + 3 * n * n for n in sizes]) == "O(n^2)"


def test_constant_program_is_o1_and_notes_missing_size_parameter():
    r = testkit.run_analyzer("complexity", "add_good.c")
    assert r["score"] == 1.0 and r["evidence"]["estimated"] == "O(1)"
    assert "no size parameter" in r["evidence"]["note"]


def test_instruction_counts_are_deterministic():
    a = testkit.run_analyzer("complexity", "add_good.c")["evidence"]["instruction_counts"]
    b = testkit.run_analyzer("complexity", "add_good.c")["evidence"]["instruction_counts"]
    assert a == b


def test_known_limitation_input_dependent_slow_path_is_invisible():
    r = testkit.run_analyzer("complexity", "add_slow_branch.c")
    assert r["score"] == 1.0          # reported O(1) although two hidden tests time out


if __name__ == "__main__":
    testkit.main(globals())
