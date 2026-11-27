from migration_pilot.profiler import profile_column, profile_table
from migration_pilot.samples import legacy_rows


def issues_by_column():
    profiles = profile_table(legacy_rows())
    return {p.name: {i.message.split(" (")[0]: i.count for i in p.issues} for p in profiles}


def test_finds_every_planted_problem():
    found = issues_by_column()
    assert found["CUST_NO"]["Duplicate IDs"] == 1
    assert found["CUST_NM"]["Missing values"] == 2
    assert found["EMAIL_ADR"]["Invalid email addresses"] == 2
    assert found["CR_LMT"]["Values that are not money"] == 1
    assert "Mixed date formats" in found["DT1"]
    assert found["ZIP"]["ZIP codes missing leading zeros"] > 0
    assert found["ST"]["State codes not in capitals"] > 0


def test_detects_column_kinds():
    kinds = {p.name: p.kind for p in profile_table(legacy_rows())}
    assert kinds == {
        "CUST_NO": "integer", "CUST_NM": "text", "ADDR1": "text", "CTY": "text", "ST": "state",
        "ZIP": "zip", "PH1": "phone", "EMAIL_ADR": "email", "CR_LMT": "currency", "DT1": "date",
        "STAT_CD": "code", "SLS_REP": "text", "TERMS_CD": "code",
    }


def test_clean_column_has_no_issues():
    assert profile_column("ID", ["1", "2", "3"]).issues == []


def test_empty_column():
    p = profile_column("X", ["", " ", ""])
    assert p.kind == "empty"
    assert p.filled_pct == 0.0
