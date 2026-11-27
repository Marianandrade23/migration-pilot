import sqlite3

import pytest

from migration_pilot.codegen import boolean_value_maps, generate, load_transform, run_generated_tests
from migration_pilot.profiler import profile_table
from migration_pilot.reconcile import reconcile, signoff_report
from migration_pilot.runner import migrate, prepare, rollback
from migration_pilot.samples import TARGET_SCHEMA, TRUE_MAPPING, legacy_rows
from migration_pilot.transforms import to_currency, to_date, to_phone, to_state, to_zip


@pytest.fixture(scope="module")
def setup(tmp_path_factory):
    rows = legacy_rows()
    value_maps, problems = boolean_value_maps(TRUE_MAPPING, profile_table(rows), TARGET_SCHEMA)
    folder = generate("test run", TRUE_MAPPING, TARGET_SCHEMA, value_maps, rows,
                      out_root=tmp_path_factory.mktemp("gen"))
    return rows, load_transform(folder), folder, problems


@pytest.mark.parametrize("fn, raw, expected", [
    (to_zip, "2108", "02108"),
    (to_state, "wi", "WI"),
    (to_phone, "920.555.1234", "(920) 555-1234"),
    (to_currency, "$12,500.00", 12500.0),
    (to_date, "20190305", "2019-03-05"),
    (to_date, "03/05/2019", "2019-03-05"),
])
def test_cleaners(fn, raw, expected):
    assert fn(raw) == (expected, None)


def test_cleaners_refuse_to_guess():
    assert to_currency("N/A")[1] is not None
    assert to_zip("abc")[1] is not None


def test_boolean_codes_understood(setup):
    *_, problems = setup
    assert problems == []


def test_generated_tests_pass(setup):
    _, _, folder, _ = setup
    passed, summary = run_generated_tests(folder)
    assert passed, summary


def test_dry_run_writes_nothing_and_holds_bad_records(setup, tmp_path):
    rows, mod, _, _ = setup
    result = prepare(rows, mod.transform_row, TARGET_SCHEMA, "test")
    assert (len(result.loaded), len(result.held)) == (194, 6)
    assert not (tmp_path / "crm.db").exists()


def test_migrate_reconcile_and_undo(setup, tmp_path):
    rows, mod, _, _ = setup
    db = tmp_path / "crm.db"
    result = migrate(rows, mod.transform_row, TARGET_SCHEMA, "test", db)
    rec = reconcile(rows, result, mod.transform_row, TARGET_SCHEMA, db)
    assert rec.passed
    assert "LOADED WITH RECORDS HELD BACK" in signoff_report(result, rec)

    again = migrate(rows, mod.transform_row, TARGET_SCHEMA, "rerun", db)
    assert len(again.loaded) == 0  # no duplicates on a second run

    assert rollback(result.batch_id, db) == 194
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0


def test_reconciliation_catches_tampering(setup, tmp_path):
    rows, mod, _, _ = setup
    db = tmp_path / "crm.db"
    result = migrate(rows, mod.transform_row, TARGET_SCHEMA, "test", db)
    con = sqlite3.connect(db)
    with con:
        con.execute("UPDATE accounts SET CreditLimit__c = CreditLimit__c + 1 WHERE rowid = 1")
        con.execute("DELETE FROM accounts WHERE rowid = 2")
    rec = reconcile(rows, result, mod.transform_row, TARGET_SCHEMA, db)
    failed = {c.name for c in rec.checks if not c.passed}
    assert {"Record count in new system", "CreditLimit__c total matches",
            "Every field matches, record by record"} <= failed
