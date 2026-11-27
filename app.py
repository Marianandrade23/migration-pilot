"""MigrationPilot review app: understand the old data, check the proposed mapping, approve it."""

from __future__ import annotations

import csv
import io
import json

import pandas as pd
import streamlit as st

from migration_pilot.corrections import record_decision
from migration_pilot.llm import get_chat_model
from migration_pilot.mapper import propose_mappings
from migration_pilot.profiler import profile_table
from migration_pilot.samples import TARGET_SCHEMA, legacy_rows

st.set_page_config(page_title="MigrationPilot", page_icon="🧭", layout="wide")
st.title("MigrationPilot")
st.caption("Move data from an old system to a new one. Review anything the agent isn't sure about.")

model = get_chat_model()
st.sidebar.markdown(f"**Mapping mode:** {'AI' if model else 'Rules (no API key set)'}")

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
    st.session_state.matches = propose_mappings(profiles, TARGET_SCHEMA, model)
    st.session_state.migration = migration_name
matches = st.session_state.matches

step1, step2 = st.tabs(["1. Understand the old data", "2. Map the fields"])

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
        st.success("Mapping approved. Your decisions were saved so the agent can learn from them.")
        st.download_button(
            "Download approved mapping (JSON)",
            json.dumps({"migration": migration_name, "mapping": final}, indent=2),
            file_name="approved_mapping.json",
        )
