"""Record every human decision on a proposed match.

These records are what MigrationPilot will learn from in Phase 3: each correction shows where the
agent was wrong and what the right answer was.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from .mapper import FieldMatch

DEFAULT_LOG = Path(__file__).resolve().parent.parent / "corrections.jsonl"


def record_decision(
    match: FieldMatch, final_target: str | None, migration: str, log_path: Path = DEFAULT_LOG,
) -> dict:
    entry = {
        "time": datetime.now(UTC).isoformat(timespec="seconds"),
        "migration": migration,
        "source": match.source,
        "proposed": match.target,
        "proposed_confidence": match.confidence,
        "final": final_target,
        "was_correct": match.target == final_target,
    }
    with Path(log_path).open("a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def load_corrections(log_path: Path = DEFAULT_LOG) -> list[dict]:
    path = Path(log_path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
