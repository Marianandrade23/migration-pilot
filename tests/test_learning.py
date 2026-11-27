import json

import pytest

from migration_pilot.benchmark import run
from migration_pilot.learn import analyst, improve, simulated_review
from migration_pilot.mapper import propose_mappings
from migration_pilot.profiler import profile_column, profile_table
from migration_pilot.samples import TARGET_SCHEMA
from migration_pilot.scenarios import all_scenarios
from migration_pilot.skill import Skill, UnsafeSkillError, check_rule, load_skill


@pytest.fixture(scope="module")
def scenarios():
    return all_scenarios()


def test_scenarios_have_complete_truth(scenarios):
    for s in scenarios:
        assert set(s.truth) == set(s.rows[0])


@pytest.mark.parametrize("kind, column, target, values, expected", [
    ("alias", "X", "NotAField", ["a"], "is not a field"),
    ("alias", "X", "Phone", ["a@b.com"] * 3, "doesn't fit"),
    ("alias", "X", "AccountNumber", ["1", "1", "2"], "must be unique"),
    ("alias", "*", "Name", ["a"], "no wildcards"),
    ("ignore", "ID", None, ["1", "2", "3"], "looks like an ID"),
    ("drop_reconciliation", "X", None, ["a"], "unknown rule type"),
])
def test_unsafe_rules_are_blocked(kind, column, target, values, expected):
    problems = check_rule(kind, column, target, Skill(), TARGET_SCHEMA, profile_column(column, values))
    assert any(expected in p for p in problems)


def test_conflicting_rule_is_blocked():
    skill = Skill(aliases={"KUNNR": "AccountNumber"})
    problems = check_rule("alias", "KUNNR", "Name", skill, TARGET_SCHEMA, None)
    assert any("conflicts" in p for p in problems)


def test_skill_file_cannot_change_pipeline_settings(tmp_path):
    path = tmp_path / "skill.json"
    path.write_text(json.dumps({"aliases": {}, "auto_approve_at": 0.0}))
    with pytest.raises(UnsafeSkillError):
        load_skill(path)


def test_learned_rule_ignored_at_use_time_if_data_does_not_fit(scenarios):
    sap = scenarios[0]
    bad = Skill(aliases={"SMTP_ADDR": "Phone"})  # sneaked past write-time checks
    m = {x.source: x for x in propose_mappings(profile_table(sap.rows), TARGET_SCHEMA, skill=bad)}
    assert m["SMTP_ADDR"].target != "Phone"


def test_analyst_puts_mistakes_first():
    cands = analyst([
        {"source": "A", "proposed": "Name", "final": "Name", "was_correct": True},
        {"source": "B", "proposed": None, "final": "Phone", "was_correct": False},
    ])
    assert [c.column for c in cands] == ["B", "A"]


def test_loop_keeps_only_helpful_rules(scenarios):
    train = [s for s in scenarios if s.split == "train"]
    corrections = [c for s in train for c in simulated_review(s, TARGET_SCHEMA)]
    skill, before, after = improve(Skill(), train, corrections, TARGET_SCHEMA)
    assert after.accuracy >= before.accuracy
    assert after.reviews < before.reviews
    assert all(c["decision"] in {"kept", "discarded (no improvement)", "blocked by safety check"}
               for c in skill.changelog)


def test_benchmark_improves_repeat_systems_without_hurting_new_ones():
    r = run(write=False)
    assert r["holdout"]["after"]["reviews"] < r["holdout"]["before"]["reviews"]
    assert r["rules_blocked_by_safety"] == 1
    for p in r["per_scenario"]:
        assert p["after"] >= p["before"]
