"""Standalone tests for analyzers/readability.py (LLM path uses a fake Ollama server)"""
import testkit


def test_heuristic_ranks_good_above_bad():
    good = testkit.run_analyzer("readability", "add_good.c", mode="heuristic")["score"]
    bad = testkit.run_analyzer("readability", "add.c", mode="heuristic")["score"]
    assert good > 0.9 and bad < 0.3


def test_llm_verdict_is_used_and_cached():
    with testkit.FakeOllama() as fo:
        cfg = fo.cfg()
        ctx_a = testkit.run_analyzer("readability", "add_good.c", llm_cfg=cfg)
        n = len(fo.calls)
        assert ctx_a["evidence"]["mode"] == "llm+heuristic"
        assert ctx_a["score"] > 0.9
        assert 0 < n
        # a fresh client with the same cache dir would hit the cache; a new ctx has a new tmp cache, so
        # check the client-level cache directly:
        from llm import OllamaClient
        c = OllamaClient(cfg, cache_dir=testkit.ROOT / ".cache" / "test_llm")
        a = c.chat("sys", "user")
        b = c.chat("sys", "user")
        assert not a["cached"] and b["cached"] and a["content"] == b["content"]
    import shutil
    shutil.rmtree(testkit.ROOT / ".cache" / "test_llm", ignore_errors=True)


def test_prompt_injection_discards_llm_and_flags():
    with testkit.FakeOllama(readability=lambda code: {"naming": 10, "comments": 10, "formatting": 10, "structure": 10}) as fo:
        r = testkit.run_analyzer("readability", "add_injection.c", llm_cfg=fo.cfg())
    assert "possible_prompt_injection" in r["flags"]
    assert r["score"] < 0.5 and all("C code reviewer" not in c["system"] for c in fo.calls)


def test_fallback_flag_when_ollama_is_down():
    r = testkit.run_analyzer("readability", "add.c", llm_cfg={"enabled": False})
    assert "readability_used_heuristic_fallback" in r["flags"] and r["score"] is not None


def test_mode_llm_skips_metric_when_ollama_is_down():
    r = testkit.run_analyzer("readability", "add.c", llm_cfg={"enabled": False}, mode="llm")
    assert r["score"] is None


def test_malformed_model_reply_falls_back():
    with testkit.FakeOllama(readability=lambda code: {"naming": "great"}) as fo:
        r = testkit.run_analyzer("readability", "add.c", llm_cfg=fo.cfg())
    assert r["evidence"]["mode"] == "heuristic" and "llm_error" in r["evidence"]


def test_known_limitation_meaningless_comments_raise_heuristic_score():
    plain = testkit.run_analyzer("readability", "add.c", mode="heuristic")["score"]
    noisy = testkit.run_analyzer("readability", "add_noisy_comments.c", mode="heuristic")["score"]
    assert noisy > plain + 0.3


if __name__ == "__main__":
    testkit.main(globals())
