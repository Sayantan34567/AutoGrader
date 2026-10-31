"""Trusted reference for the problem 'add two integers'.

Spec decision (printed in the report): the correct answer is the MATHEMATICAL
sum of the two inputs. Each input fits a signed 32-bit int, but the sum may
not. Signed overflow is undefined behaviour in C, so the expected output for
"2147483647 1" is 2147483648 (a correct program must use a wider type) and
never -2147483648.

Every problem module must provide: SAMPLE_INPUT, solve, valid_input,
corner_cases, fuzz_input, gen_input, explain.
"""
import random

INT_MIN, INT_MAX = -2**31, 2**31 - 1
SAMPLE_INPUT = "7 5\n"


def solve(inp):
    a, b = (int(x) for x in inp.split())
    return f"{a + b}\n"


def valid_input(inp):
    """True if `inp` is a legal input for the problem (used to vet LLM-proposed tests)."""
    parts = inp.split()
    if len(parts) != 2 or len(inp) > 200:
        return False
    try:
        return all(INT_MIN <= int(p) <= INT_MAX for p in parts)
    except ValueError:
        return False


def corner_cases():
    """category -> inputs, in a fixed order (reproducibility)."""
    return {
        "zero": ["0 0\n", "0 5\n", "-5 0\n"],
        "negatives": ["-1 -1\n", "-7 3\n", "3 -7\n", "-2147483648 0\n"],
        "boundaries": ["2147483647 0\n", "0 2147483647\n", "-2147483648 2147483647\n"],
        "int_overflow": ["2147483647 1\n", "-2147483648 -1\n", "2147483647 2147483647\n"],
        "whitespace": ["3   4\n", "\t3 \t 4\n", "3 4", "  3 4  \n", "3 4\r\n", "3\n4\n"],
    }


def fuzz_input(rng):
    edges = [0, 1, -1, INT_MAX, INT_MIN, INT_MAX - 1, INT_MIN + 1]

    def pick():
        return rng.choice(edges) if rng.random() < 0.3 else rng.randint(INT_MIN, INT_MAX)
    return f"{pick()} {pick()}\n"


def gen_input(n, rng):
    """Input of 'size' n for the complexity estimator. This problem has no size
    parameter, so every n yields the same shape of input (a stated limitation)."""
    return SAMPLE_INPUT


def explain(inp, expected, got, note=""):
    try:
        a, b = (int(x) for x in inp.split())
    except Exception:
        a = b = None
    if a is not None and not (INT_MIN <= a + b <= INT_MAX):
        return (f"{a} + {b} = {a + b} does not fit in a 32-bit signed int, so `a + b` on `int` "
                "overflows (undefined behaviour in C). Read into `long long` or check "
                "`b <= INT_MAX - a` before adding.")
    if got.strip() == "":
        return "The program printed nothing for this input (did it reach printf?)."
    if got.split() == expected.split():
        return "The value is right but the output format differs (check spaces / the trailing newline)."
    if not inp.endswith("\n"):
        return "Input has no trailing newline; make sure the program does not depend on one."
    return "Output differs from the correct sum. Re-check the arithmetic and the input parsing."
