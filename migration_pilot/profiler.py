"""Step 1: understand the old data before anything moves.

Profiles every source column (what kind of data it holds, how full it is, example values) and
flags data problems. This is plain code, not AI, so results are repeatable and easy to trust.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

DATE_FORMATS = {
    "MM/DD/YYYY": re.compile(r"^\d{2}/\d{2}/\d{4}$"),
    "YYYYMMDD": re.compile(r"^(19|20)\d{6}$"),
    "YYYY-MM-DD": re.compile(r"^\d{4}-\d{2}-\d{2}$"),
}
PHONE_FORMATS = {
    "(555) 555-5555": re.compile(r"^\(\d{3}\) \d{3}-\d{4}$"),
    "555-555-5555": re.compile(r"^\d{3}-\d{3}-\d{4}$"),
    "555.555.5555": re.compile(r"^\d{3}\.\d{3}\.\d{4}$"),
    "5555555555": re.compile(r"^\d{10}$"),
}
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
MONEY = re.compile(r"^\$?\d{1,3}(,\d{3})*(\.\d{2})?$|^\$?\d+(\.\d{2})?$")
US_STATES = set(
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM "
    "NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split()
)


@dataclass
class Issue:
    severity: str  # high | medium | low
    message: str
    count: int


@dataclass
class ColumnProfile:
    name: str
    kind: str
    filled_pct: float
    unique_pct: float
    examples: list[str]
    detail: str = ""
    issues: list[Issue] = field(default_factory=list)


def _share(values: list[str], test) -> float:
    return sum(1 for v in values if test(v)) / len(values) if values else 0.0


def _detect_kind(values: list[str]) -> tuple[str, str]:
    """Return (kind, detail) for the non-empty values of a column."""
    if not values:
        return "empty", ""
    date_hits = {f: sum(1 for v in values if p.match(v)) for f, p in DATE_FORMATS.items()}
    if sum(date_hits.values()) / len(values) >= 0.9:
        used = [f for f, n in date_hits.items() if n]
        return "date", ", ".join(used)
    phone_hits = {f: sum(1 for v in values if p.match(v)) for f, p in PHONE_FORMATS.items()}
    if sum(phone_hits.values()) / len(values) >= 0.9:
        return "phone", ", ".join(f for f, n in phone_hits.items() if n)
    if _share(values, lambda v: "@" in v) >= 0.9:
        return "email", ""
    if _share(values, lambda v: v.upper() in US_STATES) >= 0.9:
        return "state", ""
    if _share(values, lambda v: v.isdigit() and 3 <= len(v) <= 5) >= 0.9 and \
            max(len(v) for v in values) == 5:
        return "zip", ""
    if _share(values, lambda v: "$" in v or "," in v) >= 0.2 and _share(values, MONEY.match) >= 0.9:
        return "currency", "stored as text"
    if _share(values, lambda v: v.isdigit()) >= 0.95:
        return "integer", ""
    distinct = set(values)
    if len(distinct) <= 10 and max(len(v) for v in values) <= 4:
        return "code", "values: " + ", ".join(sorted(distinct))
    return "text", ""


def profile_column(name: str, raw: list[str]) -> ColumnProfile:
    values = [v.strip() for v in raw if v is not None and v.strip() != ""]
    total = len(raw)
    kind, detail = _detect_kind(values)
    counts = Counter(values)
    prof = ColumnProfile(
        name=name,
        kind=kind,
        filled_pct=round(100 * len(values) / total, 1) if total else 0.0,
        unique_pct=round(100 * len(counts) / len(values), 1) if values else 0.0,
        examples=[v for v, _ in counts.most_common(3)],
        detail=detail,
    )

    missing = total - len(values)
    if missing:
        prof.issues.append(Issue("medium", "Missing values", missing))

    looks_like_id = kind == "integer" and prof.unique_pct >= 95
    dupes = sum(n - 1 for n in counts.values() if n > 1)
    if looks_like_id and dupes:
        prof.issues.append(Issue("high", "Duplicate IDs", dupes))

    if kind == "date" and "," in detail:
        prof.issues.append(Issue("medium", f"Mixed date formats ({detail})", len(values)))
    if kind == "phone" and "," in detail:
        prof.issues.append(Issue("low", "Phone numbers in different formats", len(values)))
    if kind == "email":
        bad = sum(1 for v in values if not EMAIL.match(v))
        if bad:
            prof.issues.append(Issue("high", "Invalid email addresses", bad))
    if kind == "zip":
        short = sum(1 for v in values if len(v) < 5)
        if short:
            prof.issues.append(Issue("high", "ZIP codes missing leading zeros", short))
    if kind == "state":
        lower = sum(1 for v in values if v != v.upper())
        if lower:
            prof.issues.append(Issue("low", "State codes not in capitals", lower))
    if kind == "currency":
        bad = sum(1 for v in values if not MONEY.match(v))
        prof.issues.append(Issue("low", "Money stored as text (needs cleaning)", len(values) - bad))
        if bad:
            prof.issues.append(Issue("high", "Values that are not money", bad))
    if kind == "text":
        not_money = [v for v in values if not MONEY.match(v)]
        if values and len(not_money) / len(values) < 0.05:
            prof.issues.append(Issue("high", "Values that are not money", len(not_money)))
    return prof


def profile_table(rows: list[dict[str, str]]) -> list[ColumnProfile]:
    if not rows:
        return []
    columns = list(rows[0].keys())
    return [profile_column(c, [r.get(c, "") for r in rows]) for c in columns]
