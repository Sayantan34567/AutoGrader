"""Helpers shared by the test_*.py files: build an analyzer context, a fake Ollama server, a tiny runner.

Every test file runs both ways:  `python test_correctness.py`  or  `pytest -q`.
The fake Ollama server speaks the same HTTP shape as the real one (/api/tags, /api/chat), so the LLM code
paths are tested without needing a model on the machine.
"""
from __future__ import annotations

import inspect
import json
import shutil
import sys
import tempfile
import threading
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import check_rules                       # noqa: E402
import coordinator                       # noqa: E402
from analyzers import REGISTRY           # noqa: E402
from context import Context, load_reference  # noqa: E402
from llm import OllamaClient             # noqa: E402

SAMPLES = ROOT / "samples"
RULES_PATH = ROOT / "rules.json"
_tmpdirs = []


def load_rules():
    return check_rules.load_rules(RULES_PATH, ROOT)[0]


def rule_params(analyzer):
    """The params the shipped rules.json gives this analyzer, merged over the analyzer defaults."""
    for m in load_rules()["metrics"]:
        if m["analyzer"] == analyzer:
            return check_rules.with_defaults(REGISTRY[analyzer]["params"], m.get("params", {}))
    return check_rules.with_defaults(REGISTRY[analyzer]["params"], {})


def make_ctx(src, llm_cfg=None):
    """Compile `src` (first pass) and return a ready Context. llm_cfg=None -> LLM disabled."""
    rules = load_rules()
    work = Path(tempfile.mkdtemp(prefix="tk_"))
    _tmpdirs.append(work)
    cfg = dict(rules.get("llm", {}))
    cfg.update(llm_cfg or {"enabled": False})
    llm = OllamaClient(cfg, cache_dir=work / "llm_cache")
    src = Path(src)
    ctx = Context(root=ROOT, src=src.resolve(), source=src.read_text(), binary=None, workdir=work,
                  rules=rules, ref=load_reference(ROOT / rules["problem"]["reference"]), llm=llm)
    fp, binary = coordinator.sanity_check(ctx, rules["first_pass"]["compile_flags"])
    ctx.binary, ctx.first_pass = binary, fp
    return ctx


def run_analyzer(name, src, llm_cfg=None, **overrides):
    src = SAMPLES / src if not Path(src).is_absolute() and (SAMPLES / src).exists() else Path(src)
    ctx = make_ctx(src, llm_cfg)
    params = rule_params(name)
    params.update(overrides)
    return REGISTRY[name]["fn"](ctx, params)


class FakeOllama:
    """Context manager: a throwaway Ollama-compatible server on a free local port."""

    def __init__(self, model="fake:1b", extra_cases=None, readability=None, summary="Fix overflow first."):
        self.model = model
        self.extra_cases = extra_cases if extra_cases is not None else [
            {"input": "2147483647 1\n", "why": "duplicate of a built-in case"},
            {"input": "1000000 2000000\n", "why": "mid-size sum"},
            {"input": "-1 2147483647\n", "why": "mixed signs at the limit"},
            {"input": "hello world\n", "why": "INVALID: not integers"},
            {"input": "99999999999 1\n", "why": "INVALID: does not fit in int"}]
        self.readability = readability  # fn(code) -> {id: score}
        self.summary = summary
        self.calls = []

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_port}"

    def __enter__(self):
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, obj):
                body = json.dumps(obj).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                self._send({"models": [{"name": outer.model}]})

            def do_POST(self):
                req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                system, user = req["messages"][0]["content"], req["messages"][1]["content"]
                seed = req.get("options", {}).get("seed")
                outer.calls.append({"system": system[:40], "seed": seed, "temperature": req["options"].get("temperature")})
                if "QA engineer" in system:
                    content = json.dumps({"cases": outer.extra_cases})
                elif "C code reviewer" in system:
                    code = user.split("<code>")[-1]
                    ids = [ln[2:].split(":")[0] for ln in user.split("Rubric:")[1].split("Problem the program")[0].strip().splitlines()]
                    scores = (outer.readability(code) if outer.readability else
                              {i: (9 if "long long add" in code else 3) for i in ids})
                    def val(i):
                        sc = scores.get(i, 5)
                        if not isinstance(sc, (int, float)):
                            return sc  # deliberately malformed reply (used by a test)
                        return {"score": sc, "reason": f"{i} looks {'fine' if sc > 6 else 'weak'}"}
                    content = json.dumps({i: val(i) for i in ids})
                elif "teaching assistant" in system:
                    content = json.dumps({"summary": outer.summary})
                elif "C programmer" in system:
                    # seed 1 returns the same solution as submissions/other_add.c (will be flagged)
                    body = ("long long x, y;\n    scanf(\"%lld %lld\", &x, &y);\n    printf(\"%lld\\n\", x + y);"
                            if seed == 1 else "int a, b;\n    if (scanf(\"%d %d\", &a, &b) == 2) {\n        for (int i = 0; i < 1; i++) printf(\"%d\\n\", a + b);\n    }")
                    content = f"```c\n#include <stdio.h>\nint main(void) {{\n    {body}\n    return 0;\n}}\n```"
                else:
                    content = "{}"
                self._send({"message": {"role": "assistant", "content": content}})

        self.server = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *a):
        self.server.shutdown()
        self.server.server_close()

    def cfg(self, **kw):
        return {"enabled": True, "host": self.url, "model": self.model, **kw}


def main(namespace):
    """Tiny runner so `python test_x.py` works without pytest."""
    failed = 0
    for name, fn in sorted(namespace.items()):
        if name.startswith("test_") and callable(fn):
            td = tempfile.mkdtemp()
            try:
                fn(Path(td)) if "tmp_path" in inspect.signature(fn).parameters else fn()
                print("PASS", name)
            except Exception:
                failed += 1
                print("FAIL", name)
                traceback.print_exc()
            finally:
                shutil.rmtree(td, ignore_errors=True)
    for d in _tmpdirs:
        shutil.rmtree(d, ignore_errors=True)
    sys.exit(1 if failed else 0)
