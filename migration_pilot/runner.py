"""Step 4: dry run, then migrate in one batch that can be undone.

Every source record ends up in exactly one place: loaded into the new system, or held back
with the reasons why. Nothing is silently dropped or half-written.
"""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_TARGET_DB = Path(__file__).resolve().parent.parent / "target_crm.db"
SQL_TYPES = {"currency": "REAL", "boolean": "INTEGER"}

TransformRow = Callable[[dict], tuple[dict, list[str]]]


@dataclass
class Held:
    source_row: int
    key: str | None
    reasons: list[str]


@dataclass
class RunResult:
    batch_id: str
    migration: str
    dry_run: bool
    source_count: int
    loaded: list[dict] = field(default_factory=list)
    held: list[Held] = field(default_factory=list)


def key_field(target: list[dict]) -> str:
    return next(str(t["name"]) for t in target if t.get("unique"))


def init_target(db_path: Path | str, target: list[dict]) -> None:
    """Create the new system's tables if they don't exist yet."""
    cols = ", ".join(f'"{t["name"]}" {SQL_TYPES.get(str(t["type"]), "TEXT")}' for t in target)
    con = sqlite3.connect(db_path)
    with con:
        con.execute(f"CREATE TABLE IF NOT EXISTS accounts ({cols}, _batch_id TEXT, _source_row INTEGER)")
        con.execute(f'CREATE UNIQUE INDEX IF NOT EXISTS ux_key ON accounts ("{key_field(target)}")')
        con.execute(
            "CREATE TABLE IF NOT EXISTS migration_batches (batch_id TEXT PRIMARY KEY, migration TEXT, "
            "started TEXT, loaded INTEGER, held INTEGER, status TEXT)"
        )
    con.close()


def existing_keys(db_path: Path | str, target: list[dict]) -> set[str]:
    if not Path(db_path).exists():
        return set()
    con = sqlite3.connect(db_path)
    try:
        return {r[0] for r in con.execute(f'SELECT "{key_field(target)}" FROM accounts')}
    except sqlite3.OperationalError:
        return set()
    finally:
        con.close()


def prepare(
    rows: list[dict], transform_row: TransformRow, target: list[dict], migration: str,
    already_loaded: set[str] = frozenset(), dry_run: bool = True,
) -> RunResult:
    """Convert and check every record without writing anything."""
    key = key_field(target)
    required = [str(t["name"]) for t in target if t.get("required")]
    result = RunResult(uuid.uuid4().hex[:12], migration, dry_run, len(rows))
    seen: set[str] = set()
    for i, row in enumerate(rows):
        record, reasons = transform_row(row)
        k = record.get(key)
        reasons = list(reasons)
        reasons += [f"{f} is required but empty" for f in required if record.get(f) in (None, "")]
        if k in seen:
            reasons.append(f"duplicate {key} {k} in this file")
        elif k in already_loaded:
            reasons.append(f"{key} {k} already exists in the new system")
        if reasons:
            result.held.append(Held(i, k, reasons))
        else:
            seen.add(k)
            result.loaded.append({**record, "_source_row": i})
    return result


def migrate(
    rows: list[dict], transform_row: TransformRow, target: list[dict], migration: str,
    db_path: Path | str = DEFAULT_TARGET_DB,
) -> RunResult:
    """Load all clean records in one transaction, tagged with a batch ID for undo."""
    init_target(db_path, target)
    result = prepare(rows, transform_row, target, migration, existing_keys(db_path, target), dry_run=False)
    names = [str(t["name"]) for t in target]
    placeholders = ", ".join("?" for _ in range(len(names) + 2))
    columns = ", ".join(f'"{n}"' for n in names) + ", _batch_id, _source_row"
    con = sqlite3.connect(db_path)
    try:
        with con:  # all or nothing
            con.executemany(
                f"INSERT INTO accounts ({columns}) VALUES ({placeholders})",
                [[r.get(n) for n in names] + [result.batch_id, r["_source_row"]] for r in result.loaded],
            )
            con.execute(
                "INSERT INTO migration_batches VALUES (?, ?, ?, ?, ?, 'loaded')",
                (result.batch_id, migration, datetime.now(UTC).isoformat(timespec="seconds"),
                 len(result.loaded), len(result.held)),
            )
    finally:
        con.close()
    return result


def rollback(batch_id: str, db_path: Path | str = DEFAULT_TARGET_DB) -> int:
    """Undo a migration batch. Returns how many records were removed."""
    con = sqlite3.connect(db_path)
    try:
        with con:
            removed = con.execute("DELETE FROM accounts WHERE _batch_id = ?", (batch_id,)).rowcount
            con.execute("UPDATE migration_batches SET status = 'rolled back' WHERE batch_id = ?", (batch_id,))
    finally:
        con.close()
    return removed
