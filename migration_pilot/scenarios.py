"""Benchmark scenarios: customer exports from different old systems moving into the same CRM.

Each system names its columns its own way (SAP uses short German-based codes like KUNNR and NAME1).
Some exports also carry extra columns that should not be migrated. Every scenario has a ground-truth
mapping, so accuracy can be measured exactly.

Training scenarios are the migrations a human reviews and corrects. Held-out scenarios are later
migrations the agent has never seen, used to measure whether what it learned actually carries over.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .samples import LEGACY_COLUMNS, TRUE_MAPPING, legacy_rows

SYSTEMS: dict[str, dict[str, str]] = {
    # SAP-style export (customer master field names, plus custom ZZ fields).
    "sap": {
        "CUST_NO": "KUNNR", "CUST_NM": "NAME1", "ADDR1": "STRAS", "CTY": "ORT01", "ST": "REGIO",
        "ZIP": "PSTLZ", "PH1": "TELF1", "EMAIL_ADR": "SMTP_ADDR", "CR_LMT": "KLIMK",
        "DT1": "ERDAT", "STAT_CD": "ZZSTATUS", "SLS_REP": "ZZSALESREP", "TERMS_CD": "ZTERM",
    },
    # NetSuite-style CSV export.
    "netsuite": {
        "CUST_NO": "entityid", "CUST_NM": "companyname", "ADDR1": "billaddr1", "CTY": "billcity",
        "ST": "billstate", "ZIP": "billzip", "PH1": "phone", "EMAIL_ADR": "email",
        "CR_LMT": "creditlimit", "DT1": "datecreated", "STAT_CD": "isactive", "SLS_REP": "salesrep",
        "TERMS_CD": "terms",
    },
    # QuickBooks-style export. Never used for training: it checks learning doesn't hurt new systems.
    "quickbooks": {
        "CUST_NO": "Customer ID", "CUST_NM": "Company Name", "ADDR1": "Bill Street", "CTY": "Bill City",
        "ST": "Bill State", "ZIP": "Bill Zip", "PH1": "Main Phone", "EMAIL_ADR": "Main Email",
        "CR_LMT": "Credit Limit", "DT1": "Customer Since", "STAT_CD": "Active Status",
        "SLS_REP": "Rep", "TERMS_CD": "Terms",
    },
}

# Columns some exports include that have no place in the CRM.
EXTRA_COLUMNS = {
    "sap": {"MANDT": lambda r: "100", "LAND1": lambda r: "US", "KTOKD": lambda r: r.choice(["0001", "0002"])},
    "netsuite": {"internalid": lambda r: str(r.randint(10_000, 99_999)), "subsidiary": lambda r: "Parent Co"},
    "quickbooks": {"Fax": lambda r: "", "Notes": lambda r: r.choice(["", "VIP", "net terms approved"])},
}


@dataclass
class Scenario:
    name: str
    system: str
    split: str  # train | holdout
    rows: list[dict[str, str]]
    truth: dict[str, str | None]


def build_scenario(name: str, system: str, split: str, seed: int, n: int = 150) -> Scenario:
    rng = random.Random(seed)
    rename = SYSTEMS[system]
    source = legacy_rows(n=n, seed=seed)
    columns = [rename[c] for c in LEGACY_COLUMNS]
    extras = EXTRA_COLUMNS[system]
    rng.shuffle(columns)  # each export orders columns differently
    rows = []
    for row in source:
        out = {rename[c]: v for c, v in row.items()}
        out.update({col: make(rng) for col, make in extras.items()})
        rows.append({c: out[c] for c in columns + list(extras)})
    truth: dict[str, str | None] = {rename[c]: TRUE_MAPPING[c] for c in LEGACY_COLUMNS}
    truth.update({col: None for col in extras})
    return Scenario(name, system, split, rows, truth)


def all_scenarios() -> list[Scenario]:
    return [
        build_scenario("SAP export #1", "sap", "train", seed=101),
        build_scenario("NetSuite export #1", "netsuite", "train", seed=202),
        build_scenario("SAP export #2", "sap", "holdout", seed=303),
        build_scenario("NetSuite export #2", "netsuite", "holdout", seed=404),
        build_scenario("QuickBooks export", "quickbooks", "holdout", seed=505),
    ]
