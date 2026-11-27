"""Cleaning functions that turn messy old values into clean values for the new system.

Each function returns (clean_value, error). If a value can't be cleaned safely, it returns
an error instead of guessing, and the record is held back for a human.
"""

from __future__ import annotations

import re
from datetime import datetime

from .profiler import EMAIL, US_STATES

Result = tuple[object, str | None]

TRUE_CODES = {"A", "ACTIVE", "Y", "YES", "T", "TRUE", "1"}
FALSE_CODES = {"I", "INACTIVE", "N", "NO", "F", "FALSE", "0", "X"}


def _blank(value: str | None) -> bool:
    return value is None or str(value).strip() == ""


def to_text(value: str | None) -> Result:
    return (None, None) if _blank(value) else (str(value).strip(), None)


def to_state(value: str | None) -> Result:
    if _blank(value):
        return None, None
    code = str(value).strip().upper()
    return (code, None) if code in US_STATES else (None, f"'{value}' is not a US state code")


def to_zip(value: str | None) -> Result:
    if _blank(value):
        return None, None
    digits = re.sub(r"\D", "", str(value))[:5]
    if not 3 <= len(digits) <= 5:
        return None, f"'{value}' is not a ZIP code"
    return digits.zfill(5), None


def to_phone(value: str | None) -> Result:
    if _blank(value):
        return None, None
    digits = re.sub(r"\D", "", str(value))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return None, f"'{value}' is not a 10-digit phone number"
    return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}", None


def to_email(value: str | None) -> Result:
    if _blank(value):
        return None, None
    email = str(value).strip().lower()
    return (email, None) if EMAIL.match(email) else (None, f"'{value}' is not a valid email")


def to_currency(value: str | None) -> Result:
    if _blank(value):
        return None, None
    cleaned = str(value).strip().replace("$", "").replace(",", "")
    try:
        return round(float(cleaned), 2), None
    except ValueError:
        return None, f"'{value}' is not a money amount"


DATE_PATTERNS = ["%m/%d/%Y", "%Y%m%d", "%Y-%m-%d", "%d.%m.%Y", "%m/%d/%y"]


def to_date(value: str | None) -> Result:
    if _blank(value):
        return None, None
    text = str(value).strip()
    for pattern in DATE_PATTERNS:
        try:
            return datetime.strptime(text, pattern).date().isoformat(), None
        except ValueError:
            continue
    return None, f"'{value}' is not a date in a known format"


def infer_boolean_map(values: set[str]) -> tuple[dict[str, bool], list[str]]:
    """Guess which codes mean true/false. Returns (map, codes it could not place)."""
    mapping, unknown = {}, []
    for v in sorted(values):
        key = v.strip().upper()
        if key in TRUE_CODES:
            mapping[v] = True
        elif key in FALSE_CODES:
            mapping[v] = False
        else:
            unknown.append(v)
    return mapping, unknown


def to_boolean(value: str | None, value_map: dict[str, bool]) -> Result:
    if _blank(value):
        return None, None
    key = str(value).strip()
    if key in value_map:
        return value_map[key], None
    return None, f"'{value}' has no agreed true/false meaning"


CLEANERS = {
    "text": to_text, "state": to_state, "zip": to_zip, "phone": to_phone, "email": to_email,
    "currency": to_currency, "date": to_date,
}
