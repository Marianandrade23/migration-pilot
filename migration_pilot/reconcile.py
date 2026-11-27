"""Step 5: prove nothing was lost, then write a sign-off report.

Checks run against the new system's actual data, not against what we meant to write:
record counts, money totals, and a field-by-field comparison of every loaded record.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from .runner import DEFAULT_TARGET_DB, RunResult, TransformRow, key_field


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


@dataclass
class Reconciliation:
    batch_id: str
    checks: list[Check] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)


def _target_rows(db_path: Path | str, batch_id: str) -> list[dict]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute("SELECT * FROM accounts WHERE _batch_id = ?", (batch_id,))]
    finally:
        con.close()


def reconcile(
    rows: list[dict], result: RunResult, transform_row: TransformRow, target: list[dict],
    db_path: Path | str = DEFAULT_TARGET_DB,
) -> Reconciliation:
    rec = Reconciliation(result.batch_id)
    stored = _target_rows(db_path, result.batch_id)
    types = {str(t["name"]): str(t["type"]) for t in target}
    key = key_field(target)

    # 1. Every source record is accounted for: loaded or held back with a reason.
    accounted = {r["_source_row"] for r in result.loaded} | {h.source_row for h in result.held}
    missing = sorted(set(range(len(rows))) - accounted)
    rec.checks.append(Check(
        "Every source record accounted for", not missing and result.source_count == len(rows),
        f"{len(rows)} in source = {len(result.loaded)} loaded + {len(result.held)} held back"
        + (f"; missing rows {missing[:10]}" if missing else ""),
    ))

    # 2. The new system holds exactly the records we loaded.
    rec.checks.append(Check(
        "Record count in new system", len(stored) == len(result.loaded),
        f"{len(stored)} records found for batch, {len(result.loaded)} expected",
    ))

    # 3. Money totals match.
    for f_name in [n for n, t in types.items() if t == "currency"]:
        expected = round(sum(r.get(f_name) or 0 for r in result.loaded), 2)
        actual = round(sum(r.get(f_name) or 0 for r in stored), 2)
        rec.checks.append(Check(
            f"{f_name} total matches", abs(expected - actual) < 0.01,
            f"source ${expected:,.2f} vs new system ${actual:,.2f}",
        ))

    # 4. Field-by-field: re-convert each source record and compare with what was stored.
    by_key = {r[key]: r for r in stored}
    mismatches = []
    for loaded in result.loaded:
        fresh, _ = transform_row(rows[loaded["_source_row"]])
        saved = by_key.get(fresh.get(key))
        if saved is None:
            mismatches.append(f"{fresh.get(key)}: not found")
            continue
        for name, value in fresh.items():
            stored_value = bool(saved[name]) if types[name] == "boolean" and saved[name] is not None \
                else saved[name]
            if stored_value != value:
                mismatches.append(f"{fresh.get(key)}.{name}: expected {value!r}, found {stored_value!r}")
    rec.checks.append(Check(
        "Every field matches, record by record", not mismatches,
        f"{len(result.loaded)} records compared" + (f"; {len(mismatches)} differences, e.g. {mismatches[:3]}"
                                                     if mismatches else ", no differences"),
    ))
    return rec


def signoff_report(result: RunResult, rec: Reconciliation) -> str:
    status = "READY TO SIGN OFF" if rec.passed and not result.held else (
        "LOADED WITH RECORDS HELD BACK" if rec.passed else "DO NOT SIGN OFF")
    lines = [
        f"# Migration sign-off: {result.migration}",
        "",
        f"**Batch:** `{result.batch_id}` · **Status:** {status}",
        "",
        f"- Source records: {result.source_count}",
        f"- Loaded: {len(result.loaded)}",
        f"- Held back for a human: {len(result.held)}",
        "",
        "## Checks",
        "",
        "| Check | Result | Detail |",
        "| --- | --- | --- |",
        *[f"| {c.name} | {'Pass' if c.passed else 'FAIL'} | {c.detail} |" for c in rec.checks],
    ]
    if result.held:
        lines += ["", "## Held back (fix in the source and re-run)", "",
                  "| Source row | Key | Reason |", "| --- | --- | --- |"]
        lines += [f"| {h.source_row + 2} | {h.key or '—'} | {'; '.join(h.reasons)} |" for h in result.held]
    return "\n".join(lines) + "\n"
