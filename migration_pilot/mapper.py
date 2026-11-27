"""Step 2: map old fields to new fields, with a confidence score for each match.

Two ways to propose matches:
- ``rules_mapper``: name and type matching with no AI (works offline, and is the baseline to beat).
- ``ai_mapper``: an LLM reads the column profiles and the target schema and proposes matches.

Either way, plain-code checks then review every match (type fits, no two fields mapped to the same
target, target really exists). Anything below the confidence bar goes to a human.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher

from .llm import ChatModel
from .profiler import ColumnProfile

AUTO_APPROVE_AT = 0.85

# Which kinds of source data can go into each kind of target field.
COMPATIBLE = {
    "text": {"text", "code", "integer"},
    "state": {"state"},
    "zip": {"zip", "integer"},
    "phone": {"phone"},
    "email": {"email"},
    "currency": {"currency", "integer"},
    "date": {"date"},
    "boolean": {"code"},
}

# Common abbreviations in legacy ERP column names.
ABBREVIATIONS = {
    "cust": "customer", "no": "number", "num": "number", "nm": "name", "addr": "address street",
    "adr": "address", "cty": "city", "st": "state", "zip": "postal code zip", "ph": "phone",
    "cr": "credit", "lmt": "limit", "dt": "date", "stat": "status active", "cd": "code",
    "sls": "sales", "rep": "rep", "terms": "payment terms", "email": "email",
}


@dataclass
class FieldMatch:
    source: str
    target: str | None
    confidence: float
    reason: str
    status: str = "needs_review"  # auto | needs_review | unmapped

    def to_dict(self) -> dict:
        return asdict(self)


def _words(text: str) -> set[str]:
    out: set[str] = set()
    for token in re.findall(r"[a-z]+", re.sub(r"([a-z])([A-Z])", r"\1 \2", text).lower()):
        out.update(ABBREVIATIONS.get(token, token).split())
    return out


def _fits(profile: ColumnProfile, field_type: str) -> bool:
    if field_type == "boolean":
        return profile.kind == "code" and len(profile.detail.split(",")) == 2
    return profile.kind in COMPATIBLE.get(field_type, set())


def rules_mapper(profiles: list[ColumnProfile], target: list[dict]) -> list[FieldMatch]:
    """Match by expanded name words plus type fit. No AI involved."""
    scored = []
    for p in profiles:
        src_words = _words(p.name)
        for t in target:
            tgt_words = _words(str(t["name"])) | _words(str(t.get("description", "")))
            overlap = len(src_words & tgt_words) / max(len(src_words), 1)
            spelling = SequenceMatcher(None, p.name.lower(), str(t["name"]).lower()).ratio()
            fits = _fits(p, str(t["type"]))
            score = 0.6 * overlap + 0.2 * spelling + (0.2 if fits else -0.5)
            scored.append((score, p.name, str(t["name"]), fits))

    matches, used_src, used_tgt = [], set(), set()
    for score, src, tgt, fits in sorted(scored, reverse=True):
        if src in used_src or tgt in used_tgt or score <= 0.2:
            continue
        used_src.add(src)
        used_tgt.add(tgt)
        why = "name and data type match" if fits else "name match only"
        matches.append(FieldMatch(src, tgt, round(min(score, 1.0), 2), why))
    for p in profiles:
        if p.name not in used_src:
            matches.append(FieldMatch(p.name, None, 0.0, "no likely match"))
    return matches


AI_SYSTEM = """You map columns from an old system's export to fields in a new system.
For every source column return the best target field, or null if none fits.
Use the column profiles (kind of data, example values) and the target field descriptions.
Be honest about uncertainty: confidence is 0 to 1, and below 0.85 means a human should check.
Return only JSON:
{"matches": [{"source": "...", "target": "..." or null, "confidence": 0.0, "reason": "..."}]}"""


def _profiles_for_prompt(profiles: list[ColumnProfile]) -> list[dict]:
    return [
        {"column": p.name, "kind": p.kind, "detail": p.detail, "filled_pct": p.filled_pct,
         "unique_pct": p.unique_pct, "examples": p.examples}
        for p in profiles
    ]


def ai_mapper(profiles: list[ColumnProfile], target: list[dict], model: ChatModel) -> list[FieldMatch]:
    user = json.dumps({"source_columns": _profiles_for_prompt(profiles), "target_fields": target})
    text = model(AI_SYSTEM, user)
    found = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not found:
        raise ValueError("Model did not return JSON.")
    raw = json.loads(found.group(0)).get("matches", [])
    by_source = {m.get("source"): m for m in raw if isinstance(m, dict)}
    matches = []
    for p in profiles:
        m = by_source.get(p.name)
        if not m:
            matches.append(FieldMatch(p.name, None, 0.0, "model gave no match"))
            continue
        conf = float(m.get("confidence", 0) or 0)
        conf = max(0.0, min(conf, 1.0))
        matches.append(FieldMatch(p.name, m.get("target"), conf, str(m.get("reason", ""))))
    return matches


def review_matches(
    matches: list[FieldMatch], profiles: list[ColumnProfile], target: list[dict],
    auto_approve_at: float = AUTO_APPROVE_AT,
) -> list[FieldMatch]:
    """Plain-code checks on every proposed match, then decide auto-approve vs human review."""
    fields = {str(t["name"]): t for t in target}
    prof = {p.name: p for p in profiles}
    taken = Counter(m.target for m in matches if m.target)

    for m in matches:
        if m.target is None:
            m.status, m.confidence = "unmapped", 0.0
            continue
        if m.target not in fields:
            m.reason += f" | '{m.target}' is not a field in the new system"
            m.target, m.confidence, m.status = None, 0.0, "unmapped"
            continue
        if not _fits(prof[m.source], str(fields[m.target]["type"])):
            m.confidence = min(m.confidence, 0.4)
            m.reason += f" | data looks like {prof[m.source].kind}, field expects {fields[m.target]['type']}"
        if taken[m.target] > 1:
            m.confidence = min(m.confidence, 0.5)
            m.reason += " | another column is mapped to the same field"
        m.status = "auto" if m.confidence >= auto_approve_at else "needs_review"
    return matches


def propose_mappings(
    profiles: list[ColumnProfile], target: list[dict], model: ChatModel | None = None,
) -> list[FieldMatch]:
    """Propose matches with AI if a model is given, otherwise with rules, then review them."""
    raw = ai_mapper(profiles, target, model) if model else rules_mapper(profiles, target)
    return review_matches(raw, profiles, target)


def accuracy(matches: list[FieldMatch], truth: dict[str, str | None]) -> float:
    """Share of source columns mapped to the correct target (used by tests and the benchmark)."""
    if not truth:
        return 0.0
    got = {m.source: m.target for m in matches}
    return sum(got.get(src) == tgt for src, tgt in truth.items()) / len(truth)
