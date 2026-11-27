from migration_pilot.corrections import load_corrections, record_decision
from migration_pilot.mapper import FieldMatch


def test_decisions_are_saved_and_loaded(tmp_path):
    log = tmp_path / "corrections.jsonl"
    record_decision(FieldMatch("DT1", "CustomerSince__c", 0.8, "date"), "CustomerSince__c", "test", log)
    record_decision(FieldMatch("STAT_CD", "PaymentTerms__c", 0.5, "code"), "IsActive__c", "test", log)
    entries = load_corrections(log)
    assert [e["was_correct"] for e in entries] == [True, False]
    assert entries[1]["final"] == "IsActive__c"


def test_no_log_yet(tmp_path):
    assert load_corrections(tmp_path / "missing.jsonl") == []
