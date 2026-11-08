"""REMEM admin dashboard (owner only; not public).
Run:  streamlit run eval_dashboard/app.py
Tabs: Pilot monitor (from a downloaded copy of the live DB) and Offline results (EdNet experiments).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from eval_dashboard import pilot  # noqa: E402

RESULTS = ROOT / "experiments" / "results"
ARTIFACTS = ROOT / "artifacts"
PILOT_DB = ROOT / "data" / "pilot" / "remem_live.db"

st.set_page_config(page_title="REMEM admin", page_icon="R", layout="wide")
st.title("REMEM — admin dashboard")
st.caption("Evidence policy: the pilot is too small for significance tests; arm comparisons below are descriptive. "
           "The scheduler claim rests on SimLab + pilot, not on EdNet alone.")

tab_pilot, tab_results, tab_sim, tab_model = st.tabs(["Pilot monitor", "Offline results (EdNet)", "SimLab", "Deployed model"])


def csv(name: str):
    p = RESULTS / name
    return pd.read_csv(p) if p.exists() else None


# ------------------------------------------------------------------ pilot
with tab_pilot:
    path = Path(st.text_input("Database copy", str(PILOT_DB)))
    if not path.exists():
        st.info("No database copy yet. Run `deploy/fetch_pilot_db.ps1` to download a snapshot from the server.")
    else:
        age_h = (time.time() - path.stat().st_mtime) / 3600
        st.caption(f"Snapshot file age: {age_h:.1f} h. Re-run the fetch script to refresh, then press R.")
        conn = pilot.open_ro(path)
        now_ms = int(time.time() * 1000)

        users = pilot.users_table(conn, now_ms)
        stu = users[users["role"] == "student"]
        health = pilot.llm_health(conn)
        adh = pilot.adherence(conn, now_ms)

        c = st.columns(5)
        c[0].metric("Student accounts", len(stu))
        c[1].metric("Consented", int(stu["consented"].sum()))
        c[2].metric("Active (answered)", int((stu["n_answers"] > 0).sum()))
        c[3].metric("Total answers", int(stu["n_answers"].sum()))
        c[4].metric("Overdue concepts", f"{adh['overdue']}/{adh['tracked']}")

        st.subheader("Users")
        st.dataframe(users, hide_index=True, width='stretch')
        silent = stu[(stu["days_since_last"].isna()) | (stu["days_since_last"] > 3)]
        if len(silent):
            st.warning("No activity in 3+ days (or never): " + ", ".join(silent["username"]))

        st.subheader("Activity per day (IST)")
        da = pilot.daily_activity(conn)
        if da.empty:
            st.write("No answers yet.")
        else:
            st.bar_chart(da.set_index("day")[["answers", "reviews"]])
            st.line_chart(da.set_index("day")[["active_users"]])

        st.subheader("Adherence")
        if adh["tracked"]:
            st.write(f"{adh['overdue']} of {adh['tracked']} tracked concepts are overdue now; "
                     f"median lateness {adh['median_days_late']:.1f} days.")
        else:
            st.write("No scheduled concepts yet.")

        st.subheader("Arms (descriptive only)")
        st.dataframe(pilot.by_arm(conn), hide_index=True, width='stretch')
        st.caption("Arms are assigned per concept at random: remem / sm2 / fixed (3-day).")

        st.subheader("Prediction calibration on review answers")
        cal = pilot.calibration(conn)
        if cal.empty:
            st.write("No review answers with predictions yet.")
        else:
            st.dataframe(cal, hide_index=True, width='stretch')
            st.line_chart(cal.set_index("bin")[["predicted", "observed"]])

        st.subheader("LLM quiz generation")
        d = st.columns(4)
        d[0].metric("Notes processed", f"{health['notes_done']}/{health['notes_total']}")
        d[1].metric("Failed notes", health["notes_failed"])
        d[2].metric("Questions", health["questions"])
        d[3].metric("Flagged by students", f"{health['flagged']} ({health['flag_rate']:.0%})" if health["questions"] else "0")
        errs = pilot.recent_errors(conn)
        if len(errs):
            st.dataframe(errs, hide_index=True, width='stretch')

        st.subheader("Final test")
        st.write("OPEN" if pilot.final_test_open(conn) else "Closed (set settings key `final_test_open`='1' on the server to open).")
        with st.expander("Recent audit events"):
            st.dataframe(pilot.recent_audit(conn), hide_index=True, width='stretch')

# ---------------------------------------------------------------- results
with tab_results:
    st.subheader("Experiment 2 — baselines (held-out)")
    b = csv("exp2_baselines.csv")
    if b is not None:
        st.dataframe(b, hide_index=True, width='stretch')
    else:
        st.write("Missing.")

    st.subheader("Experiment 3 — forgetting model variants")
    m = csv("exp3_forgetting_metrics.csv")
    if m is not None:
        split = st.radio("Split", sorted(m["split"].unique()), index=len(m["split"].unique()) - 1, horizontal=True)
        subset = st.radio("Subset", sorted(m["subset"].unique()), horizontal=True)
        t = m[(m["split"] == split) & (m["subset"] == subset)].sort_values("logloss")
        st.dataframe(t, hide_index=True, width='stretch')
        st.caption("Lower logloss / brier / ece is better. Read together with the honest-findings note in Appendix F of the spec.")
    cg = csv("exp3_calibration_by_gap.csv")
    if cg is not None:
        st.subheader("Calibration by time gap")
        models = st.multiselect("Models", sorted(cg["model"].unique()), default=sorted(cg["model"].unique())[:3])
        piv = cg[cg["model"].isin(models)].pivot(index="bin", columns="model", values="abs_gap")
        st.bar_chart(piv)
    co = csv("exp3_coefficients.csv")
    if co is not None:
        st.subheader("Stability coefficients (EdNet fit)")
        st.dataframe(co, hide_index=True, width='stretch')
    g = csv("exp1_accuracy_by_gap.csv")
    if g is not None:
        st.subheader("Experiment 1 — accuracy by gap")
        st.dataframe(g, hide_index=True, width='stretch')
    if (RESULTS / "exp1_gaps.png").exists():
        st.image(str(RESULTS / "exp1_gaps.png"))
    log = csv("run_log.csv")
    if log is not None:
        with st.expander("Run log"):
            st.dataframe(log, hide_index=True, width='stretch')

# ----------------------------------------------------------------- simlab
with tab_sim:
    st.caption("Simulated students with known true memory. Findings concern simulated learners only.")
    md = csv("exp10_matched.csv")
    fr = csv("exp10_frontier.csv")
    if md is None or fr is None:
        st.write("Run `python experiments/exp10_simlab.py` first.")
    else:
        st.subheader("Reviews saved by REMEM (theta 0.85) at matched time-below-target")
        t = md[md["matched_on"] == "below_target"].groupby(["gen", "phi", "baseline"]).agg(
            saved_mean=("reviews_saved_pct", "mean"), saved_min=("reviews_saved_pct", "min"), saved_max=("reviews_saved_pct", "max")).round(1).reset_index()
        st.dataframe(t, hide_index=True, width='stretch')
        st.caption("Negative = REMEM needed more reviews. Differences inside the seed range are not demonstrated. "
                   "Matching on delayed-test recall is unreliable (non-monotone) and not reported.")
        gen = st.radio("Generator", sorted(fr["gen"].unique()), horizontal=True)
        phi = st.radio("phi", sorted(fr["phi"].unique()), index=1, horizontal=True)
        f = fr[(fr["gen"] == gen) & (fr["phi"] == phi)].groupby(["policy", "knob"], as_index=False).mean(numeric_only=True)
        st.subheader("Trade-off: reviews per concept vs time below target")
        import altair as alt
        st.altair_chart(alt.Chart(f).mark_line(point=True).encode(
            x=alt.X("reviews_per_concept", title="reviews per concept (60 days)"), y=alt.Y("frac_below_target", title="share of time below 0.85"),
            color="policy", tooltip=["policy", "knob", "reviews_per_concept", "frac_below_target", "final_recall"]), width='stretch')
        rc = csv("exp10_recovery.csv")
        if rc is not None:
            st.subheader("Estimator recovery (rank correlation of fitted S with true S)")
            st.dataframe(rc.groupby(["gen", "phi"])[["spearman_S", "beta_fit"]].mean().round(2).reset_index(), hide_index=True, width='stretch')

# ------------------------------------------------------------------ model
with tab_model:
    p = ARTIFACTS / "stability_model.json"
    if p.exists():
        sm = json.loads(p.read_text())
        st.subheader("Deployed starter prior (D15)")
        st.json(sm)
        beta = float(sm.get("beta", 0.5))
        k = 0.9 ** (-1 / beta) - 1
        S = st.slider("Stability S (days)", 1.0, 60.0, 8.0)
        days = list(range(0, 61))
        st.line_chart(pd.DataFrame({"day": days, "retrievability": [(1 + k * d / S) ** (-beta) for d in days]}).set_index("day"))
        st.caption("R(t) = (1 + k·t/S)^(−β) with R(S) = 0.9. The EdNet-fitted model (β≈0.02) is nearly flat, which is why the app uses this prior.")
