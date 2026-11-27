"""The self-improvement loop: turn human corrections into rules, and keep only rules that help.

Three roles, in the spirit of self-improving agent skills:
- Executor: runs the mapper on the training migrations and scores it.
- Analyst: reads the human corrections and proposes one candidate rule per mistake.
- Mutator: adds one rule at a time. A rule is kept only if it passes the safety check AND
  improves the score without making any training migration worse. Otherwise it's discarded.
Every decision is written to the skill's changelog.
"""

from __future__ import annotations

from dataclasses import dataclass

from .mapper import accuracy, propose_mappings
from .profiler import ColumnProfile, profile_table
from .scenarios import Scenario
from .skill import Skill, check_rule


@dataclass
class Candidate:
    kind: str  # alias | ignore
    column: str
    target: str | None
    evidence: str


@dataclass
class Score:
    accuracy: float
    reviews: int
    per_scenario: dict[str, float]


def score(skill: Skill, scenarios: list[Scenario], schema: list[dict]) -> Score:
    """Executor: map every scenario with the current skill and measure it."""
    per, reviews = {}, 0
    for s in scenarios:
        matches = propose_mappings(profile_table(s.rows), schema, skill=skill)
        per[s.name] = accuracy(matches, s.truth)
        reviews += sum(m.status == "needs_review" for m in matches)
    return Score(sum(per.values()) / len(per), reviews, per)


def simulated_review(scenario: Scenario, schema: list[dict], skill: Skill | None = None) -> list[dict]:
    """A stand-in for a human reviewer: fixes every wrong match and confirms every flagged one.

    In real use these records come from the review screen (corrections.jsonl).
    """
    out = []
    for m in propose_mappings(profile_table(scenario.rows), schema, skill=skill):
        final = scenario.truth[m.source]
        if m.target != final or m.status == "needs_review":
            out.append({"migration": scenario.name, "source": m.source, "proposed": m.target,
                        "final": final, "was_correct": m.target == final})
    return out


def analyst(corrections: list[dict]) -> list[Candidate]:
    """Propose one rule per correction (wrong matches first, then confirmations)."""
    seen, wrong, confirmed = set(), [], []
    for c in corrections:
        key = (c["source"].upper(), c["final"])
        if key in seen:
            continue
        seen.add(key)
        if c["final"] is None:
            cand = Candidate("ignore", c["source"], None, f"human said {c['source']} is not migrated")
        else:
            verb = "corrected" if not c["was_correct"] else "confirmed"
            cand = Candidate("alias", c["source"], c["final"], f"human {verb} {c['source']} -> {c['final']}")
        (confirmed if c["was_correct"] else wrong).append(cand)
    return wrong + confirmed


def _profiles_for(column: str, scenarios: list[Scenario]) -> ColumnProfile | None:
    for s in scenarios:
        for p in profile_table(s.rows):
            if p.name.upper() == column.upper():
                return p
    return None


def improve(
    skill: Skill, train: list[Scenario], corrections: list[dict], schema: list[dict],
) -> tuple[Skill, Score, Score]:
    """Mutator loop. Returns (improved skill, score before, score after)."""
    skill = skill.copy()
    start = current = score(skill, train, schema)
    for cand in analyst(corrections):
        rule = f"{cand.column} -> {cand.target}" if cand.kind == "alias" else f"ignore {cand.column}"
        entry = {"rule": rule, "why": cand.evidence}
        problems = check_rule(cand.kind, cand.column, cand.target, skill, schema,
                              _profiles_for(cand.column, train))
        if problems:
            skill.changelog.append({**entry, "decision": "blocked by safety check", "detail": problems})
            continue

        trial = skill.copy()
        if cand.kind == "alias":
            trial.aliases[cand.column.upper()] = str(cand.target)
        else:
            trial.ignore.add(cand.column.upper())
        new = score(trial, train, schema)

        no_regression = all(new.per_scenario[k] >= current.per_scenario[k] for k in new.per_scenario)
        better = new.accuracy > current.accuracy or (
            new.accuracy == current.accuracy and new.reviews < current.reviews)
        detail = (f"accuracy {current.accuracy:.1%} -> {new.accuracy:.1%}, "
                  f"reviews {current.reviews} -> {new.reviews}")
        if better and no_regression:
            trial.changelog = skill.changelog + [{**entry, "decision": "kept", "detail": detail}]
            skill, current = trial, new
        else:
            skill.changelog.append({**entry, "decision": "discarded (no improvement)", "detail": detail})
    return skill, start, current
