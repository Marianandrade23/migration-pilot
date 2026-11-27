import json

import pytest

from migration_pilot.llm import scripted_model
from migration_pilot.mapper import FieldMatch, accuracy, propose_mappings, review_matches
from migration_pilot.profiler import profile_table
from migration_pilot.samples import TARGET_SCHEMA, TRUE_MAPPING, legacy_rows


@pytest.fixture(scope="module")
def profiles():
    return profile_table(legacy_rows())


def test_rules_mapper_on_sample(profiles):
    matches = propose_mappings(profiles, TARGET_SCHEMA)
    assert accuracy(matches, TRUE_MAPPING) == 1.0
    assert any(m.status == "needs_review" for m in matches)


def test_ai_mapper_uses_model_output(profiles):
    reply = {"matches": [{"source": s, "target": t, "confidence": 0.95, "reason": "clear"}
                         for s, t in TRUE_MAPPING.items()]}
    matches = propose_mappings(profiles, TARGET_SCHEMA, scripted_model([json.dumps(reply)]))
    assert accuracy(matches, TRUE_MAPPING) == 1.0
    assert all(m.status == "auto" for m in matches)


def test_wrong_data_type_is_sent_to_review(profiles):
    m = review_matches([FieldMatch("EMAIL_ADR", "Phone", 0.99, "guess")], profiles, TARGET_SCHEMA)[0]
    assert m.status == "needs_review"
    assert m.confidence <= 0.4
    assert "expects phone" in m.reason


def test_two_columns_on_one_field_both_need_review(profiles):
    matches = review_matches(
        [FieldMatch("CUST_NM", "Name", 0.95, "a"), FieldMatch("SLS_REP", "Name", 0.9, "b")],
        profiles, TARGET_SCHEMA,
    )
    assert all(m.status == "needs_review" for m in matches)


def test_made_up_target_field_is_rejected(profiles):
    m = review_matches([FieldMatch("CUST_NM", "CompanyTitle", 0.97, "guess")], profiles, TARGET_SCHEMA)[0]
    assert m.target is None
    assert m.status == "unmapped"


def test_missing_model_answer_is_unmapped(profiles):
    reply = {"matches": [{"source": "CUST_NO", "target": "AccountNumber", "confidence": 0.9}]}
    matches = propose_mappings(profiles, TARGET_SCHEMA, scripted_model([json.dumps(reply)]))
    assert sum(m.status == "unmapped" for m in matches) == len(profiles) - 1


def test_bad_model_output_raises(profiles):
    with pytest.raises(ValueError):
        propose_mappings(profiles, TARGET_SCHEMA, scripted_model(["no idea, sorry"]))
