"""The agent's learned migration skill, and the safety checks every learned rule must pass.

A skill holds two kinds of rules learned from human corrections:
- aliases: "column KUNNR goes to AccountNumber"
- ignore: "column MANDT is never migrated"

Safety is checked twice, following the finding that self-improving agents can learn harmful
shortcuts and reuse them later: once when a rule is written, and again when it is used.
A skill can only contain these two rule types, so learning can never switch off review,
validation or reconciliation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .profiler import ColumnProfile

SKILL_PATH = Path(__file__).resolve().parent.parent / "skill" / "learned_skill.json"
ALLOWED_KEYS = {"version", "aliases", "ignore", "changelog"}


@dataclass
class Skill:
    aliases: dict[str, str] = field(default_factory=dict)
    ignore: set[str] = field(default_factory=set)
    changelog: list[dict] = field(default_factory=list)

    def copy(self) -> Skill:
        return Skill(dict(self.aliases), set(self.ignore), list(self.changelog))

    def to_json(self) -> dict:
        return {"version": 1, "aliases": dict(sorted(self.aliases.items())),
                "ignore": sorted(self.ignore), "changelog": self.changelog}


class UnsafeSkillError(ValueError):
    pass


def load_skill(path: Path = SKILL_PATH) -> Skill:
    path = Path(path)
    if not path.exists():
        return Skill()
    data = json.loads(path.read_text())
    unknown = set(data) - ALLOWED_KEYS
    if unknown:
        raise UnsafeSkillError(f"Skill file has fields it is not allowed to have: {sorted(unknown)}")
    return Skill(dict(data.get("aliases", {})), set(data.get("ignore", [])), list(data.get("changelog", [])))


def save_skill(skill: Skill, path: Path = SKILL_PATH) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(skill.to_json(), indent=2) + "\n")
    return path


def check_rule(
    kind: str, column: str, target_field: str | None, skill: Skill, schema: list[dict],
    profile: ColumnProfile | None,
) -> list[str]:
    """Write-time safety check. Returns the reasons a rule is unsafe (empty list = safe)."""
    from .mapper import _fits  # local import avoids a cycle

    problems = []
    if kind not in {"alias", "ignore"}:
        problems.append(f"unknown rule type '{kind}'")
    if not column or not column.strip() or any(ch in column for ch in "*?%"):
        problems.append("rule must name one exact column (no wildcards)")
    key = column.upper()
    fields = {str(t["name"]): t for t in schema}
    if kind == "alias":
        if target_field not in fields:
            problems.append(f"'{target_field}' is not a field in the new system")
        else:
            spec = fields[target_field]
            if profile is not None and not _fits(profile, str(spec["type"])):
                problems.append(f"column data ({profile.kind}) doesn't fit {target_field} ({spec['type']})")
            if spec.get("unique") and profile is not None and profile.unique_pct < 95:
                problems.append(f"{target_field} must be unique, but the column is only "
                                f"{profile.unique_pct}% unique")
        if key in skill.aliases and skill.aliases[key] != target_field:
            problems.append(f"conflicts with existing rule {key} -> {skill.aliases[key]}")
        if key in skill.ignore:
            problems.append(f"conflicts with existing rule: ignore {key}")
    if kind == "ignore":
        if key in skill.aliases:
            problems.append(f"conflicts with existing rule {key} -> {skill.aliases[key]}")
        if profile is not None and profile.filled_pct > 0 and profile.unique_pct >= 95 and \
                profile.kind in {"integer", "text"}:
            problems.append("refusing to ignore a column that looks like an ID or name")
    return problems
