"""Run the benchmark: does learning from one migration make the next one better?

1. Map the training migrations, and let a (simulated) human correct them.
2. Run the self-improvement loop on those corrections.
3. Map migrations the agent has never seen, before and after learning, and compare.

Usage: python -m migration_pilot.benchmark
"""

from __future__ import annotations

import json
from pathlib import Path

from .learn import improve, score, simulated_review
from .samples import TARGET_SCHEMA
from .scenarios import all_scenarios
from .skill import Skill, save_skill

ROOT = Path(__file__).resolve().parent.parent
REPORT_MD = ROOT / "docs" / "BENCHMARK.md"
REPORT_JSON = ROOT / "docs" / "benchmark.json"


def run(write: bool = True) -> dict:
    scenarios = all_scenarios()
    train = [s for s in scenarios if s.split == "train"]
    holdout = [s for s in scenarios if s.split == "holdout"]

    corrections = [c for s in train for c in simulated_review(s, TARGET_SCHEMA)]
    # One deliberately wrong correction, like a tired reviewer would make: an account-group code
    # (only 2 distinct values) mapped to the unique account number. The safety check must block it.
    corrections.append({"migration": "SAP export #1", "source": "KTOKD", "proposed": None,
                        "final": "AccountNumber", "was_correct": False})
    learned, train_before, train_after = improve(Skill(), train, corrections, TARGET_SCHEMA)

    before = score(Skill(), holdout, TARGET_SCHEMA)
    after = score(learned, holdout, TARGET_SCHEMA)

    decisions = [c["decision"] for c in learned.changelog]
    result = {
        "mode": "rules (no AI model)",
        "corrections_used": len(corrections),
        "rules_kept": decisions.count("kept"),
        "rules_discarded": decisions.count("discarded (no improvement)"),
        "rules_blocked_by_safety": decisions.count("blocked by safety check"),
        "train": {"before": vars(train_before), "after": vars(train_after)},
        "holdout": {"before": vars(before), "after": vars(after)},
        "per_scenario": [
            {"scenario": s.name, "system": s.system, "seen_in_training": s.system != "quickbooks",
             "before": before.per_scenario[s.name], "after": after.per_scenario[s.name]}
            for s in holdout
        ],
    }
    if write:
        save_skill(learned)
        REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
        REPORT_JSON.write_text(json.dumps(result, indent=2) + "\n")
        REPORT_MD.write_text(render(result, learned))
    return result


def _scenario_row(p: dict) -> str:
    seen = "Yes" if p["seen_in_training"] else "No"
    return f"| {p['scenario']} | {seen} | {p['before']:.1%} | {p['after']:.1%} |"


def _rule_row(c: dict) -> str:
    detail = c["detail"] if isinstance(c["detail"], str) else "; ".join(c["detail"])
    return f"| {c['rule']} | {c['decision']} | {detail} |"


def render(r: dict, skill: Skill) -> str:
    hb, ha = r["holdout"]["before"], r["holdout"]["after"]
    lines = [
        "# Benchmark",
        "",
        "Does correcting one migration make the next one better? The agent learns from human",
        "corrections on two training migrations (SAP and NetSuite exports), then maps migrations it",
        f"has never seen. Mode: {r['mode']}. Human corrections are simulated from the known answers.",
        "",
        "## Unseen migrations",
        "",
        "| | Before learning | After learning |",
        "| --- | --- | --- |",
        f"| Mapping accuracy | {hb['accuracy']:.1%} | {ha['accuracy']:.1%} |",
        f"| Fields a human must review | {hb['reviews']} | {ha['reviews']} |",
        "",
        "| Migration | Same system seen in training? | Before | After |",
        "| --- | --- | --- | --- |",
        *[_scenario_row(p) for p in r["per_scenario"]],
        "",
        "## What the agent learned",
        "",
        f"From {r['corrections_used']} corrections: {r['rules_kept']} rules kept, "
        f"{r['rules_discarded']} discarded because they didn't help, "
        f"{r['rules_blocked_by_safety']} blocked by the safety check.",
        "",
        "| Rule | Decision | Detail |",
        "| --- | --- | --- |",
        *[_rule_row(c) for c in skill.changelog],
        "",
        "## Limits of this benchmark",
        "",
        "- The data is synthetic and the human reviewer is simulated from the known answers.",
        "- Learned rules are exact column names. They carry over to later exports from the same",
        "  system (SAP after SAP), which is how real migrations run, in waves. They do not help on",
        "  a new system: QuickBooks shows no gain, and no harm.",
        "- One wrong correction was added on purpose to test the safety check.",
        "- This run uses rule-based matching. AI matching is supported but not benchmarked here.",
        "",
        "Run it yourself: `python -m migration_pilot.benchmark`",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    out = run()
    hb, ha = out["holdout"]["before"], out["holdout"]["after"]
    print(f"Unseen migrations: accuracy {hb['accuracy']:.1%} -> {ha['accuracy']:.1%}, "
          f"reviews {hb['reviews']} -> {ha['reviews']}")
    print(f"Rules kept {out['rules_kept']}, discarded {out['rules_discarded']}, "
          f"blocked by safety {out['rules_blocked_by_safety']}")
