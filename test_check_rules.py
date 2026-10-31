"""Standalone tests for check_rules.py"""
import copy
import json

import testkit
from check_rules import RulesError, load_rules, validate_rules


def good():
    return testkit.load_rules()


def errors_for(mutator):
    rules = copy.deepcopy(good())
    mutator(rules)
    return validate_rules(rules, testkit.ROOT)


def test_shipped_rules_are_valid():
    errors, warnings = validate_rules(good(), testkit.ROOT)
    assert errors == [] and warnings == []


def test_weights_must_sum_to_one():
    errors, _ = errors_for(lambda r: r["metrics"][0].update(weight=0.9))
    assert any("sum to 1.00" in e for e in errors)


def test_disabled_metric_weight_is_not_counted():
    def m(r):
        r["metrics"][-1]["enabled"] = False
        r["metrics"][0]["weight"] = 0.30
    assert errors_for(m)[0] == []


def test_unknown_analyzer_is_rejected():
    errors, _ = errors_for(lambda r: r["metrics"][1].update(analyzer="nope"))
    assert any("unknown analyzer" in e for e in errors)


def test_wrong_param_type_and_range():
    errors, _ = errors_for(lambda r: r["metrics"][-1]["params"].update(flag_threshold="high"))
    assert any("flag_threshold" in e for e in errors)
    errors, _ = errors_for(lambda r: r["metrics"][-1]["params"].update(flag_threshold=1.5))
    assert any("above the maximum" in e for e in errors)


def test_unknown_param_is_only_a_warning():
    errors, warnings = errors_for(lambda r: r["metrics"][1]["params"].update(flgs="-Wall"))
    assert errors == [] and any("flgs" in w for w in warnings)


def test_missing_reference_and_bad_llm_settings():
    errors, _ = errors_for(lambda r: r["problem"].update(reference="problems/missing.py"))
    assert any("reference" in e for e in errors)
    errors, _ = errors_for(lambda r: r["llm"].update(model=""))
    assert any("llm.model" in e for e in errors)


def test_invalid_json_gives_a_clear_error(tmp_path):
    p = tmp_path / "r.json"
    p.write_text('{"problem": ')
    try:
        load_rules(p, testkit.ROOT)
        raise AssertionError("expected RulesError")
    except RulesError as e:
        assert "not valid JSON" in str(e)


def test_rules_hash_changes_with_content_not_formatting(tmp_path):
    a = load_rules(testkit.RULES_PATH, testkit.ROOT)[1]
    p = tmp_path / "r.json"
    p.write_text(json.dumps(good(), indent=None))
    assert load_rules(p, testkit.ROOT)[1] == a
    r = good(); r["time_limit_s"] = 2; p.write_text(json.dumps(r))
    assert load_rules(p, testkit.ROOT)[1] != a


if __name__ == "__main__":
    testkit.main(globals())
