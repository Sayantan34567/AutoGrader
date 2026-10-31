# AutoGrader: a rule-driven, reproducible grader for C programs

Give it a student's `.c` file and an instructor-written `rules.json`. It compiles and runs the program
in a sandbox, checks it with nine analyzers, and writes one weighted grade plus feedback
(`reports/<name>.json` for machines, `reports/<name>.txt` for the student).
A local LLM (Ollama) reviews readability, proposes extra edge cases, writes reference solutions for the
copy check and drafts a tutor summary. **Same submission + same rules = same grade.**

```
AutoGrader/
├── main.py                 Streamlit web UI
├── coordinator.py          the main agent: rules check -> first pass -> dispatch -> collation -> reports
├── check_rules.py          validates rules.json (weights sum to 1, known analyzers, parameter types)
├── rules.json              instructor's rules: problem, limits, LLM settings, metrics, weights, thresholds
├── analyzers/              one file per metric (auto-discovered)
│   ├── correctness.py        hidden I/O tests
│   ├── compiler_warnings.py  gcc -Wall -Wextra -Werror diagnostics
│   ├── static_analysis.py    cyclomatic complexity / function length (lizard) + cppcheck
│   ├── modularity.py         helper functions present and used
│   ├── edge_cases.py         corner cases + seeded fuzz + LLM-proposed inputs, judged by a reference solution
│   ├── complexity.py         valgrind instruction counts at growing sizes, fitted to O(1)..O(n^3)
│   ├── memory_safety.py      ASan + UBSan + valgrind leak check
│   ├── readability.py        Ollama rubric review blended with a heuristic
│   └── originality.py        token-winnowing similarity vs other students and LLM-written solutions
├── sandbox.py llm.py cparse.py context.py report.py    shared helpers
├── problems/add.py         trusted reference solution, corner cases, fuzzer, explanations
├── submissions/            add.c, other_add.c (comparison corpus for the originality check)
├── samples/                sample submissions: good, overflow, loop, crash, leak, copy, ...
├── tests/add/              hidden tests (NN.in / NN.out)
├── reports/                output of the agent on the samples
├── docs/usefulness_limitations.json   text embedded in every report
├── test_*.py               standalone analyzer tests + end-to-end coordinator test
├── requirements.txt        Python packages (each one explained in comments)
└── setup_ubuntu.sh         one-shot installer for Ubuntu
```

## 1. Install

**Lab PC (Ubuntu):** open a terminal in this folder and run
```bash
./setup_ubuntu.sh                 # apt packages, .venv, pip install -r requirements.txt, Ollama, model pull
./setup_ubuntu.sh --no-ollama     # same without the local LLM
```
No sudo on the lab PC? Ask for `build-essential valgrind` (cppcheck optional). Then
`python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt`. Without Ollama everything
still runs; the readability metric falls back to a heuristic and the report says so.

**Windows 11 laptop:** the sandbox needs Linux, so work inside WSL2.
1. PowerShell **as Administrator**: `wsl --install -d Ubuntu-24.04`, reboot, create your Linux user.
2. Copy this folder into the Linux home (not `/mnt/c`, it is slow): `cp -r /mnt/c/Users/<you>/Downloads/AutoGrader ~/`
3. In Ubuntu: `cd ~/AutoGrader && ./setup_ubuntu.sh`
4. Edit with VS Code + the "WSL" extension (`code .` inside Ubuntu). The web UI started in WSL opens in your
   normal Windows browser at `http://localhost:8501`.

Install Ollama **inside WSL** (the script does this); a Windows-side Ollama is usually not reachable from WSL.
Choose the model to match your RAM and write the same name into `rules.json` -> `llm.model`:
8 GB `llama3.2:3b` (default), 16 GB+ `llama3.1:8b`.

## 2. Run

```bash
source .venv/bin/activate
streamlit run main.py                                   # web UI: grade one, batch, rules editor
python coordinator.py submissions/add.c                 # command line, one file
python coordinator.py samples/*.c -v                    # many files, show the agent's steps
python coordinator.py submissions/add.c --no-llm        # without Ollama
python check_rules.py --ollama                          # validate rules.json and check the model is pulled
```
Reports land in `reports/`. Exit codes: 2 invalid rules, 3 not running on Linux.

## 3. Tests
```bash
python test_coordinator.py     # end to end (about 35 s); also: pytest -q   (runs every test_*.py)
python test_originality.py     # any single analyzer on its own
```
The LLM code paths are tested against a fake Ollama server (`testkit.py`), so they run on any machine.
Tests named `test_known_limitation_*` reproduce the limitations quoted in the report.

## 4. The agent, step by step
1. **Rules check** (`check_rules.py`): errors stop the run, warnings (unknown parameter names) do not.
2. **First pass** (sanity check): `gcc -O2 -Wall -Wextra -std=c11`, a smoke run on the sample input under the time
   and memory limits, and a static check for `main`, a reader, a writer and a `return`.
   If the program does not compile or the smoke run times out (`suspected_infinite_loop`), execution-based
   analyzers are skipped and the report is marked PARTIAL; source-only analyzers still run.
3. **Dispatch**: execution analyzers run one after another (parallel load would make wall-clock limits flaky),
   source-only analyzers run in parallel. Each returns `score`, `evidence`, `feedback`, `suggestions`, `flags`.
4. **Collation**: weighted sum. A metric that could not run (tool missing, analyzer crash) is excluded and
   its weight is redistributed; this is visible in the report. Counter-examples from all analyzers are merged,
   deduplicated and sorted smallest-input-first.
5. **Reports**: JSON + text, both free of timestamps, PIDs and absolute paths.

### Where the local LLM is used (and where it is not)
| Use | Safeguard |
|---|---|
| Readability review against the rubric in `rules.json` | blended 70/30 with a heuristic; code is passed as data; verdict discarded and flagged if the code tries to instruct the reviewer |
| Extra tricky test inputs | the input must pass the reference's `valid_input()`; expected output always comes from the reference solution, never the LLM; same cached inputs for every student; not in the score unless `llm_cases_count_in_score` is true |
| Reference solutions for the copy check (seeds 1..N) | cached; a match only raises a flag, it does not cost points by default |
| Tutor summary | written from the report's own facts, does not affect the grade |

The grade itself never depends on an LLM *deciding correctness*. Every LLM answer is requested at temperature 0
with a fixed seed and cached under `.cache/llm/` (key = hash of model + prompts + options). Delete `.cache/` to force new calls.

## 5. Editing the rules
`rules.json` holds everything an instructor changes: problem statement, `tests_dir`, time and memory limits, LLM
model, and the metric list with `weight` (must sum to 1.00) and `params`. Each analyzer declares its parameters
(type, range, default) in its `PARAMS` dict; `check_rules.py` enforces them. Set `"enabled": false` on a metric to
switch it off (then re-balance the weights). The Rules editor tab in the web UI validates before saving.

**Add a metric:** create `analyzers/my_metric.py` with `NEEDS_EXECUTION`, `PARAMS` and `analyze(ctx, params)`
(see `analyzers/__init__.py`), then add `{"analyzer": "my_metric", "weight": ..., "params": {...}}` to `rules.json`.
**Add a problem:** copy `problems/add.py` (needs `SAMPLE_INPUT, solve, valid_input, corner_cases, fuzz_input, gen_input, explain`),
add tests under `tests/<name>/`, and point a new rules file at them.

## 6. Design decisions worth defending
- **Expected output for `INT_MAX + 1` is `2147483648`.** Signed overflow is undefined behaviour in C, so
  `-2147483648` can never be "expected"; a correct program must use a wider type.
- **Instruction counts, not seconds,** for the complexity estimate (deterministic).
- **Sandbox:** `prlimit` (CPU, address space, file size, no core), wall-clock timeout, own process group killed on
  timeout, private temp dir, output captured to files and capped. It does **not** isolate the network or the
  filesystem: grade untrusted code inside a container or VM in production.
- **Sanitizer runs:** ASan/UBSan binaries are run without the address-space limit (ASan needs a huge
  virtual range) but with the CPU and wall-clock limits.

## 7. Sample submissions and what the agent says (generated with `--no-llm`; with Ollama the readability numbers differ)

| File | Grade | What the report shows |
|---|---|---|
| `add_good.c` | 99.9 | helper function, `long long`, clean under ASan/UBSan |
| `add_leak.c` | 92.9 | correct output, but LeakSanitizer + valgrind report a leak |
| `add_slow_branch.c` | 90.3 | complexity O(1) 10/10 although 2 hidden tests time out (limitation 2) |
| `add_copy.c` | 83.6 | renamed copy of `other_add.c`: `suspected_copy`, originality 0 |
| `add_minimal.c` | 77.6 | independent trivial solution flagged as a copy (limitation 3) |
| `add_hardcoded.c` | 77.5 | memorised tests: 20/20 correctness, edge cases expose it (limitation 1) |
| `add.c` (the assignment's example) | 74.8 | `INT_MAX + 1` overflow: counter-example `2147483647 1`, expected `2147483648` |
| `add_noisy_comments.c` | 68.5 | filler comments inflate readability (limitation 4); also a near-copy of `add.c` |
| `add_injection.c` | 66.5 | comment tries to instruct the reviewer: `possible_prompt_injection`; also a near-copy of `add.c` |
| `add_crash.c` | 37.6 | NULL dereference: SIGSEGV on every input, ASan/UBSan findings |
| `add_infinite.c` | 37.6 | PARTIAL report, `suspected_infinite_loop`, execution analyzers skipped |
| `add_syntax_error.c` | 27.6 | PARTIAL report, `compile_failed` |

## 8. Known limitations (reproduced by the samples and tests)
1. `add_hardcoded.c` memorises the hidden tests: 20/20 on correctness, exposed only by the edge-case metric.
2. `add_slow_branch.c`: complexity says O(1) although two hidden tests time out (the problem has no size parameter).
3. `add_minimal.c`: an independent, obvious solution is flagged as a copy (similarity 1.00) on a very short problem.
4. `add_noisy_comments.c`: meaningless comments raise the heuristic readability score from 0.19 to 0.56.

Also: a small local model can be inconsistent between model versions (the cache hides this on one machine, not across machines);
reports produced with and without Ollama differ (the report flags which).

## 9. Troubleshooting
| Symptom | Fix |
|---|---|
| `environment error: The sandbox needs Linux` | run inside WSL2 / Ubuntu, not native Windows |
| `Ollama not reachable` | `ollama serve` (second terminal) or `ollama list`; the agent still works without it |
| `model 'x' is not pulled` | `ollama pull x`, or set `llm.model` in `rules.json` to a model from `ollama list` |
| `valgrind missing` in the report | `sudo apt install valgrind` (the complexity metric is skipped meanwhile) |
| Sanitizer build failed | `sudo apt install build-essential` (provides libasan/libubsan) |
| Port 8501 busy | `streamlit run main.py --server.port 8502` |
| Slow first LLM call | the model is loading into RAM; later calls and repeat runs (cache) are fast |
