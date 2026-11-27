"""Sample migration: a legacy ERP customer export moving into a CRM Account object.

The legacy export uses short, cryptic column names and has the data problems real exports have:
mixed date formats, lost ZIP leading zeros, inconsistent phone numbers, money stored as text,
duplicate IDs, bad emails and missing names.
"""

from __future__ import annotations

import csv
import random
from pathlib import Path

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"
LEGACY_CSV = SAMPLES_DIR / "legacy_customers.csv"

LEGACY_COLUMNS = [
    "CUST_NO", "CUST_NM", "ADDR1", "CTY", "ST", "ZIP", "PH1", "EMAIL_ADR",
    "CR_LMT", "DT1", "STAT_CD", "SLS_REP", "TERMS_CD",
]

TARGET_SCHEMA: list[dict[str, object]] = [
    {"name": "AccountNumber", "type": "text", "required": True, "unique": True,
     "description": "Customer's account ID carried over from the old system."},
    {"name": "Name", "type": "text", "required": True,
     "description": "Company name of the customer."},
    {"name": "BillingStreet", "type": "text", "description": "Street address for billing."},
    {"name": "BillingCity", "type": "text", "description": "City for billing."},
    {"name": "BillingState", "type": "state", "description": "Two-letter US state code."},
    {"name": "BillingPostalCode", "type": "zip", "description": "5-digit US ZIP code, stored as text."},
    {"name": "Phone", "type": "phone", "description": "Main phone number."},
    {"name": "Email__c", "type": "email", "description": "Main contact email."},
    {"name": "CreditLimit__c", "type": "currency", "description": "Credit limit in US dollars."},
    {"name": "CustomerSince__c", "type": "date", "description": "Date the customer account was opened."},
    {"name": "IsActive__c", "type": "boolean", "description": "Whether the customer is currently active."},
    {"name": "SalesRep__c", "type": "text", "description": "Name of the assigned sales rep."},
    {"name": "PaymentTerms__c", "type": "text", "description": "Payment terms, such as Net 30."},
]

# Ground truth for the sample, used by tests and (later) the benchmark.
TRUE_MAPPING = {
    "CUST_NO": "AccountNumber", "CUST_NM": "Name", "ADDR1": "BillingStreet", "CTY": "BillingCity",
    "ST": "BillingState", "ZIP": "BillingPostalCode", "PH1": "Phone", "EMAIL_ADR": "Email__c",
    "CR_LMT": "CreditLimit__c", "DT1": "CustomerSince__c", "STAT_CD": "IsActive__c",
    "SLS_REP": "SalesRep__c", "TERMS_CD": "PaymentTerms__c",
}

_CITIES = [("Green Bay", "WI", "54301"), ("Boston", "MA", "02108"), ("Newark", "NJ", "07102"),
           ("Chicago", "IL", "60601"), ("Hartford", "CT", "06103"), ("Austin", "TX", "73301"),
           ("Madison", "WI", "53703"), ("Portland", "ME", "04101")]
_NAMES = ["North Lake Foods", "Badger Logistics", "Harbor Dairy", "Summit Brewing", "Prairie Goods",
          "Cedar Retail Co", "Granite Supply", "Maple Packaging", "Union Beverages", "River Bakery"]
_REPS = ["J. Smith", "A. Garcia", "M. Chen", "K. Patel"]
_TERMS = ["N30", "N45", "N60", "COD"]


def _phone(rng: random.Random) -> str:
    a, b, c = rng.randint(200, 989), rng.randint(200, 999), rng.randint(1000, 9999)
    return rng.choice([f"({a}) {b}-{c}", f"{a}-{b}-{c}", f"{a}.{b}.{c}", f"{a}{b}{c}"])


def _date(rng: random.Random) -> str:
    y, m, d = rng.randint(2012, 2025), rng.randint(1, 12), rng.randint(1, 28)
    return rng.choice([f"{m:02d}/{d:02d}/{y}", f"{y}{m:02d}{d:02d}"])


def legacy_rows(n: int = 200, seed: int = 7) -> list[dict[str, str]]:
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        city, state, zip_code = rng.choice(_CITIES)
        name = f"{rng.choice(_NAMES)} {i + 1}"
        rows.append({
            "CUST_NO": f"{100000 + i}",
            "CUST_NM": name,
            "ADDR1": f"{rng.randint(10, 9999)} {rng.choice(['Main', 'Oak', 'Mason', 'Lake', 'Elm'])} St",
            "CTY": city,
            "ST": state if rng.random() > 0.15 else state.lower(),
            "ZIP": str(int(zip_code)),  # Excel-style export drops leading zeros
            "PH1": _phone(rng),
            "EMAIL_ADR": f"ap@{name.split()[0].lower()}{i + 1}.com",
            "CR_LMT": rng.choice([f"${rng.randint(5, 250) * 1000:,}.00", str(rng.randint(5, 250) * 1000)]),
            "DT1": _date(rng),
            "STAT_CD": rng.choices(["A", "I"], weights=[8, 2])[0],
            "SLS_REP": rng.choice(_REPS),
            "TERMS_CD": rng.choice(_TERMS),
        })
    # Planted problems.
    rows[3]["CUST_NM"] = ""
    rows[57]["CUST_NM"] = ""
    rows[12]["EMAIL_ADR"] = "accounts payable"
    rows[140]["EMAIL_ADR"] = "billing@"
    rows[88]["CUST_NO"] = rows[87]["CUST_NO"]  # duplicate ID
    rows[120]["CR_LMT"] = "N/A"
    return rows


def write_sample(path: Path = LEGACY_CSV) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=LEGACY_COLUMNS)
        writer.writeheader()
        writer.writerows(legacy_rows())
    return path


if __name__ == "__main__":
    print(f"Wrote {write_sample()}")
