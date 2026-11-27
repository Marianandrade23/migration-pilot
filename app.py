"""MigrationPilot app: understand the old data, map fields, migrate safely, and sign off."""

from __future__ import annotations

import csv
import io
import json

import pandas as pd
import streamlit as st

from migration_pilot.codegen import boolean_value_maps, generate, load_transform, run_generated_tests
from migration_pilot.corrections import record_decision
from migration_pilot.llm import get_chat_model
from migration_pilot.mapper import propose_mappings
from migration_pilot.profiler import profile_table
from migration_pilot.reconcile import reconcile, signoff_report
from migration_pilot.runner import DEFAULT_TARGET_DB, existing_keys, migrate, prepare, rollback
from migration_pilot.samples import TARGET_SCHEMA, legacy_rows
from migration_pilot.skill import load_skill

st.set_page_config(page_title="MigrationPilot", page_icon="🧭", layout="wide")
st.title("MigrationPilot")
st.caption("Move data from an old system to a new one. Review anything the agent isn't sure about.")

model = get_chat_model()
skill = load_skill()
st.sidebar.markdown(f"**Mapping mode:** {'AI' if model else 'Rules (no API key set)'}")
st.sidebar.markdown(f"**Learned rules:** {len(skill.aliases) + len(skill.ignore)}")

uploaded = st.sidebar.file_uploader("Old system export (CSV)", type="csv")
if uploaded:
    rows = list(csv.DictReader(io.StringIO(uploaded.getvalue().decode("utf-8-sig"))))
    migration_name = uploaded.name
else:
    rows = legacy_rows()
    migration_name = "sample: legacy ERP customers -> CRM accounts"
st.sidebar.caption(f"{len(rows)} rows · {migration_name}")

profiles = profile_table(rows)
if "matches" not in st.session_state or st.session_state.get("migration") != migration_name:
    st.session_state.matches = propose_mappings(profiles, TARGET_SCHEMA, model, skill=skill)
    st.session_state.migration = migration_name
    st.session_state.pop("approved", None)
    st.session_state.pop("result", None)
matches = st.session_state.matches

step1, step2, step3, step4 = st.tabs(
    ["1. Understand the old data", "2. Map the fields", "3. Convert and migrate", "4. Sign-off report"]
)

with step1:
    issues = [(p.name, i) for p in profiles for i in p.issues]
    c1, c2, c3 = st.columns(3)
    c1.metric("Columns", len(profiles))
    c2.metric("Data problems found", len(issues))
    c3.metric("High severity", sum(i.severity == "high" for _, i in issues))
    st.dataframe(
        pd.DataFrame([
            {"Column": p.name, "Looks like": p.kind, "Filled %": p.filled_pct,
             "Unique %": p.unique_pct, "Examples": ", ".join(p.examples), "Notes": p.detail}
            for p in profiles
        ]),
        use_container_width=True, hide_index=True,
    )
    if issues:
        st.subheader("Fix before migrating")
        order = {"high": 0, "medium": 1, "low": 2}
        for col, issue in sorted(issues, key=lambda x: order[x[1].severity]):
            icon = {"high": "🔴", "medium": "🟠", "low": "🟡"}[issue.severity]
            st.write(f"{icon} **{col}**: {issue.message} ({issue.count} rows)")

with step2:
    auto = [m for m in matches if m.status == "auto"]
    review = [m for m in matches if m.status != "auto"]
    st.write(f"**{len(auto)}** matches approved automatically · **{len(review)}** need your review")

    st.dataframe(
        pd.DataFrame([
            {"Old column": m.source, "New field": m.target or "—", "Confidence": m.confidence,
             "Status": m.status.replace("_", " "), "Why": m.reason}
            for m in sorted(matches, key=lambda m: m.confidence, reverse=True)
        ]),
        use_container_width=True, hide_index=True,
    )

    options = ["(don't migrate)"] + [str(t["name"]) for t in TARGET_SCHEMA]
    final: dict[str, str | None] = {m.source: m.target for m in auto}
    if review:
        st.subheader("Your review")
        for m in review:
            default = options.index(m.target) if m.target in options else 0
            choice = st.selectbox(
                f"{m.source} (proposed: {m.target or 'none'}, confidence {m.confidence:.2f})",
                options, index=default, key=f"pick_{m.source}",
            )
            final[m.source] = None if choice == options[0] else choice

    if st.button("Approve mapping", type="primary"):
        for m in review:
            record_decision(m, final[m.source], migration_name)
        st.session_state.approved = final
        st.success("Mapping approved. Your decisions were saved so the agent can learn from them.")
        st.download_button(
            "Download approved mapping (JSON)",
            json.dumps({"migration": migration_name, "mapping": final}, indent=2),
            file_name="approved_mapping.json",
        )

with step3:
    approved = st.session_state.get("approved")
    if not approved:
        st.info("Approve the mapping in step 2 first.")
    else:
        value_maps, problems = boolean_value_maps(approved, profiles, TARGET_SCHEMA)
        for problem in problems:
            st.warning(problem)
        folder = generate(migration_name, approved, TARGET_SCHEMA, value_maps, rows)
        transform = load_transform(folder)
        passed, summary = run_generated_tests(folder)
        (st.success if passed else st.error)(f"Generated conversion tests: {summary}")
        with st.expander("Conversion code that will run"):
            st.code((folder / "transform.py").read_text(), language="python")

        dry = prepare(rows, transform.transform_row, TARGET_SCHEMA, migration_name,
                      existing_keys(DEFAULT_TARGET_DB, TARGET_SCHEMA))
        c1, c2 = st.columns(2)
        c1.metric("Dry run: ready to load", len(dry.loaded))
        c2.metric("Dry run: held back", len(dry.held))
        if dry.held:
            st.dataframe(
                pd.DataFrame([{"Source row": h.source_row + 2, "Key": h.key, "Reason": "; ".join(h.reasons)}
                              for h in dry.held]),
                use_container_width=True, hide_index=True,
            )
        if st.button("Migrate", type="primary", disabled=not passed):
            result = migrate(rows, transform.transform_row, TARGET_SCHEMA, migration_name)
            st.session_state.result = result
            st.session_state.recon = reconcile(rows, result, transform.transform_row, TARGET_SCHEMA)
            st.success(f"Loaded {len(result.loaded)} records in batch {result.batch_id}. See step 4.")
        result = st.session_state.get("result")
        if result and st.button(f"Undo batch {result.batch_id}"):
            removed = rollback(result.batch_id)
            st.session_state.pop("result")
            st.warning(f"Undone: {removed} records removed from the new system.")

with step4:
    result = st.session_state.get("result")
    if not result:
        st.info("Run the migration in step 3 to get a sign-off report.")
    else:
        report = signoff_report(result, st.session_state.recon)
        st.markdown(report)
        st.download_button("Download sign-off report", report, file_name="signoff_report.md")
