"""Ollama client (local LLM backend) with an on-disk response cache.

Reproducibility rule: every call uses temperature 0 (unless an analyzer asks
otherwise) and a fixed seed, AND every answer is cached on disk keyed by
sha256(model, prompts, options). Re-grading the same submission under the same
rules therefore returns the stored answer even if the model is re-pulled or the
GPU/CPU gives slightly different numbers.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import requests

PROMPT_VERSION = "v2"  # bump to invalidate old cache entries when prompts change
DEFAULTS = {"enabled": True, "host": "http://localhost:11434", "model": "llama3.2:3b",
            "temperature": 0, "seed": 42, "timeout_s": 180, "num_predict": 600}


def _norm_model(name):
    name = name.strip()
    return name if ":" in name else name + ":latest"


class OllamaClient:
    def __init__(self, cfg=None, cache_dir=".cache/llm"):
        self.cfg = {**DEFAULTS, **(cfg or {})}
        self.cache_dir = Path(cache_dir)
        self._status = None  # memoised (ok, message)

    # ---- status -------------------------------------------------------------
    @property
    def model(self):
        return self.cfg["model"]

    def status(self, refresh=False):
        """(ok, message). ok means: server reachable AND the model is pulled."""
        if self._status is not None and not refresh:
            return self._status
        if not self.cfg.get("enabled", True):
            self._status = (False, "LLM disabled in rules.json (llm.enabled = false)")
            return self._status
        try:
            r = requests.get(self.cfg["host"].rstrip("/") + "/api/tags", timeout=3)
            r.raise_for_status()
            names = {m.get("name", "") for m in r.json().get("models", [])}
        except Exception as e:
            self._status = (False, f"Ollama not reachable at {self.cfg['host']} "
                                   f"({type(e).__name__}); start it with `ollama serve`")
            return self._status
        if _norm_model(self.model) not in {_norm_model(n) for n in names}:
            self._status = (False, f"model '{self.model}' is not pulled; run "
                                   f"`ollama pull {self.model}` (installed: {', '.join(sorted(names)) or 'none'})")
        else:
            self._status = (True, f"Ollama ready, model {self.model}")
        return self._status

    def available(self):
        return self.status()[0]

    # ---- chat ---------------------------------------------------------------
    def _key(self, model, system, user, temperature, seed, json_mode):
        blob = json.dumps([PROMPT_VERSION, model, system, user, temperature, seed, json_mode],
                          sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()

    def chat(self, system, user, *, json_mode=True, temperature=None, seed=None, model=None):
        """Returns {"ok", "content", "cached", "error", "model"}. Never raises."""
        model = model or self.model
        temperature = self.cfg["temperature"] if temperature is None else temperature
        seed = self.cfg["seed"] if seed is None else seed
        key = self._key(model, system, user, temperature, seed, json_mode)
        path = self.cache_dir / f"{key}.json"
        if path.exists():
            try:
                return {"ok": True, "content": json.loads(path.read_text())["content"],
                        "cached": True, "error": None, "model": model}
            except Exception:
                pass  # corrupt cache entry -> ask again
        if not self.available():
            return {"ok": False, "content": "", "cached": False, "error": self.status()[1], "model": model}
        body = {"model": model, "stream": False,
                "options": {"temperature": temperature, "seed": seed,
                            "num_predict": self.cfg["num_predict"]},
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}]}
        if json_mode:
            body["format"] = "json"
        try:
            r = requests.post(self.cfg["host"].rstrip("/") + "/api/chat", json=body,
                              timeout=self.cfg["timeout_s"])
            r.raise_for_status()
            content = r.json()["message"]["content"]
        except Exception as e:
            return {"ok": False, "content": "", "cached": False,
                    "error": f"{type(e).__name__}: {e}"[:200], "model": model}
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"model": model, "content": content}))
        except OSError:
            pass
        return {"ok": True, "content": content, "cached": False, "error": None, "model": model}

    def chat_json(self, system, user, **kw):
        """Like chat() but parses the reply as a JSON object (tolerates ```json fences)."""
        res = self.chat(system, user, json_mode=True, **kw)
        res["data"] = None
        if res["ok"]:
            res["data"] = parse_json_object(res["content"])
            if res["data"] is None:
                res["ok"], res["error"] = False, "model did not return valid JSON"
        return res


def parse_json_object(text):
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except Exception:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                obj = json.loads(m.group())
                return obj if isinstance(obj, dict) else None
            except Exception:
                return None
    return None


def extract_c_code(text):
    fence = re.search(r"```(?:c|C)?\s*\n(.*?)```", text, re.S)
    return (fence.group(1) if fence else text).strip() + "\n"
