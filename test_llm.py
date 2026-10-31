"""Standalone tests for llm.py (Ollama client) against the fake server"""
import testkit
from llm import OllamaClient, extract_c_code, parse_json_object


def test_unreachable_server_is_reported_not_raised(tmp_path):
    c = OllamaClient({"host": "http://127.0.0.1:9", "model": "x:1b"}, cache_dir=tmp_path)
    ok, msg = c.status()
    assert not ok and "not reachable" in msg
    assert c.chat("s", "u")["ok"] is False


def test_model_not_pulled_is_explained(tmp_path):
    with testkit.FakeOllama(model="other:1b") as fo:
        ok, msg = OllamaClient(fo.cfg(model="missing:7b"), cache_dir=tmp_path).status()
    assert not ok and "ollama pull missing:7b" in msg


def test_untagged_model_name_matches_latest(tmp_path):
    with testkit.FakeOllama(model="llama3.2:latest") as fo:
        assert OllamaClient(fo.cfg(model="llama3.2"), cache_dir=tmp_path).status()[0]


def test_answers_are_cached_and_use_fixed_options(tmp_path):
    with testkit.FakeOllama() as fo:
        c = OllamaClient(fo.cfg(temperature=0, seed=42), cache_dir=tmp_path)
        a, b = c.chat("system", "user"), c.chat("system", "user")
        assert not a["cached"] and b["cached"] and len(fo.calls) == 1
        assert fo.calls[0]["seed"] == 42 and fo.calls[0]["temperature"] == 0
        assert OllamaClient(fo.cfg(), cache_dir=tmp_path).chat("system", "user")["cached"]   # survives a restart


def test_disabled_client_never_calls_the_server(tmp_path):
    c = OllamaClient({"enabled": False}, cache_dir=tmp_path)
    assert c.available() is False and c.chat("s", "u")["ok"] is False


def test_json_and_code_extraction():
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_object('sure! {"a": 2} hope that helps') == {"a": 2}
    assert parse_json_object("not json") is None and parse_json_object("[1]") is None
    assert "int main" in extract_c_code("text\n```c\nint main(){}\n```\nmore")


if __name__ == "__main__":
    testkit.main(globals())
