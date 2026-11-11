"""REMEM admin dashboard (owner only).   Run:  streamlit run eval_dashboard/app.py

Pages: Pilot (live data pulled from the server), EdNet results, SimLab, Model.
Pilot numbers are descriptive: ten people is too few for significance tests.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import html  # noqa: E402
import importlib  # noqa: E402
from eval_dashboard import pilot  # noqa: E402

importlib.reload(pilot)
from eval_dashboard.server import Server, ServerError  # noqa: E402

load_dotenv(ROOT / ".env")
RESULTS, ARTIFACTS = ROOT / "experiments" / "results", ROOT / "artifacts"
LIVE_DB = ROOT / "data" / "pilot" / "remem_live.db"
ACCENT, INK, AMBER, GREEN, RED = "#3a3fe0", "#12162f", "#a85a00", "#17784f", "#b3261e"

st.set_page_config(page_title="REMEM admin", page_icon="R", layout="wide")
st.markdown(f"""
<style>
  #MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"] {{ display: none !important; }}
  header[data-testid="stHeader"] {{ background: transparent; height: 0; }}
  .block-container {{ max-width: 1080px; padding-top: 2.2rem; padding-bottom: 5rem; }}
  html, body, [class*="css"] {{ font-family: "Avenir Next", "Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif; }}
  h1 {{ font-size: 2rem !important; font-weight: 800 !important; letter-spacing: -.02em; padding: 0 0 .2rem !important; }}
  h2, h3 {{ letter-spacing: -.01em; font-weight: 750 !important; }}
  h2 {{ font-size: 1.3rem !important; margin-top: 2.2rem !important; }}
  [data-testid="stMetricLabel"] p {{ font-size: .9rem; color: #545c7c; }}
  [data-testid="stMetricValue"] {{ font-size: 1.9rem; font-weight: 800; letter-spacing: -.02em; }}
  [data-testid="stSidebar"] {{ background: #ffffff; border-right: 1px solid #d3d8ea; }}
  [data-testid="stSidebar"] > div:first-child {{ padding-top: .4rem; }}
  [data-testid="stSidebarNav"] {{ padding-top: 0; }}
  [data-testid="stSidebarNav"]::before {{ content: "remem admin"; display: block; padding: 1.2rem 1.1rem 1rem; font-size: 1.45rem; font-weight: 800; letter-spacing: -.03em; color: {ACCENT}; }}
  [data-testid="stSidebarNavLink"] {{ margin: 2px .6rem; padding: .6rem .8rem; border-radius: 10px; font-weight: 600; color: #12162f; min-height: 44px; }}
  [data-testid="stSidebarNavLink"]:hover {{ background: #eef0fb; }}
  [data-testid="stSidebarNavLink"][aria-current="page"] {{ background: #e7e9fb; color: {ACCENT}; }}
  [data-testid="stSidebarNavLink"][aria-current="page"] span {{ color: {ACCENT}; font-weight: 700; }}
  [data-testid="stSidebarUserContent"] {{ padding: .6rem 1.1rem 1rem; }}
  .conn {{ border-top: 1px solid #d3d8ea; padding-top: .9rem; font-size: .9rem; font-weight: 600; line-height: 1.5; }}
  .conn span:not(.dot) {{ font-weight: 400; color: #545c7c; word-break: break-all; }}
  .dot {{ display: inline-block; width: .55rem; height: .55rem; border-radius: 50%; background: {GREEN}; margin-right: .5rem; }}
  .dot.off {{ background: #a8aecd; }}
  .finding {{ border-top: 1px solid #d3d8ea; padding: 1rem 0 .3rem; }}
  .finding .fq {{ font-weight: 700; font-size: 1.05rem; }}
  .finding .fv {{ font-weight: 700; font-size: .95rem; margin: .1rem 0 .4rem; }}
  .finding p {{ margin: .2rem 0; }}
  .note {{ color: #545c7c; font-size: .95rem; margin: -.2rem 0 .8rem; }}
  .flag {{ padding: .65rem .9rem; border-radius: 10px; margin: .35rem 0; background: #fff; border: 1px solid #d3d8ea; font-size: .97rem; }}
  .flag.warn {{ border-color: {AMBER}; }}
  .flag b {{ color: {AMBER}; }}
  .st-key-danger {{ border: 1.5px solid {RED} !important; border-radius: 14px; background: #fff; padding: .4rem .6rem; }}
  .st-key-danger h3 {{ color: {RED}; font-size: 1.1rem !important; }}
  .st-key-open_reset button, [data-testid="stDialog"] button[kind="primaryFormSubmit"] {{ background: {RED}; border-color: {RED}; color: #fff; font-weight: 700; }}
  .st-key-open_reset button:hover, [data-testid="stDialog"] button[kind="primaryFormSubmit"]:hover {{ background: #8f1d17; border-color: #8f1d17; color: #fff; }}
  button[kind="primary"] {{ font-weight: 700; }}
</style>""", unsafe_allow_html=True)


def csv(name: str):
    p = RESULTS / name
    return pd.read_csv(p) if p.exists() else None


def note(text: str) -> None:
    st.markdown(f'<p class="note">{text}</p>', unsafe_allow_html=True)


def ago(seconds: float) -> str:
    if seconds < 90:
        return "just now"
    if seconds < 5400:
        return f"{seconds / 60:.0f} min ago"
    if seconds < 172800:
        return f"{seconds / 3600:.0f} hours ago"
    return f"{seconds / 86400:.0f} days ago"


# ------------------------------------------------------------------ connection to the live server
def get_server() -> Server | None:
    """Connect with the details in .env if present (no form needed); otherwise the Pilot page shows a connect form."""
    srv = st.session_state.get("srv")
    if srv is not None:
        return srv
    url, pw = os.getenv("REMEM_SERVER_URL"), os.getenv("REMEM_ADMIN_PASSWORD")
    if url and pw and "auto_failed" not in st.session_state:
        try:
            s = Server(url)
            s.login(os.getenv("REMEM_ADMIN_USER", "aryan"), pw)
            st.session_state["srv"] = s
            return s
        except (ServerError, OSError, ValueError) as e:
            st.session_state["auto_failed"] = str(e)
    return None


srv: Server | None = get_server()


def connect_panel() -> None:
    st.title("Pilot")
    st.markdown("### Connect to the server")
    if st.session_state.get("auto_failed"):
        st.error(f"The details in .env did not work: {st.session_state['auto_failed']}")
    note("The dashboard reads live data from your REMEM server using your admin account. "
         "To skip this step next time, add <code>REMEM_SERVER_URL</code> and <code>REMEM_ADMIN_PASSWORD</code> to the <code>.env</code> file and restart the dashboard.")
    with st.form("connect"):
        url = st.text_input("Server address", value=os.getenv("REMEM_SERVER_URL", ""), placeholder="https://your-server")
        user = st.text_input("Admin username", value=os.getenv("REMEM_ADMIN_USER", "aryan"))
        pw = st.text_input("Admin password", type="password")
        if st.form_submit_button("Connect", type="primary"):
            try:
                s = Server(url)
                s.login(user, pw)
                st.session_state["srv"] = s
                st.session_state.pop("auto_failed", None)
                st.rerun()
            except (ServerError, OSError, ValueError) as e:
                st.error(f"Could not connect: {e}")


def refresh() -> bool:
    try:
        srv.download_snapshot(LIVE_DB)
        st.session_state["fetched_at"] = time.time()
        return True
    except (ServerError, OSError) as e:
        st.session_state["flash"] = ("err", f"Could not load the latest data: {e}")
        return False


flash = st.session_state.pop("flash", None)


# ------------------------------------------------------------------ pilot
@st.dialog("Reset test data")
def reset_dialog(server: Server) -> None:
    st.markdown(f'<span style="color:{RED};font-weight:700">Proceed with caution. This cannot be undone.</span>', unsafe_allow_html=True)
    st.write("This deletes the notes, quizzes, answers and review schedule of the accounts you choose. "
             "The accounts and their passwords stay, so people can still sign in.")
    try:
        accts = server.accounts()
    except ServerError as e:
        st.error(str(e))
        return
    labels = {f"{a['username']} ({a['answers']} answers, {a['concepts']} concepts)": a["username"] for a in accts if a["role"] != "demo"}   # test accounts are never listed
    with st.form("reset_form", border=False):                              # one submit, so nothing depends on partial reruns
        scope = st.radio("Which accounts?", ["Choose accounts", "Every account"], horizontal=True)
        picked = st.multiselect("Accounts to reset (used when 'Choose accounts' is selected)", list(labels))
        clear_consent = st.checkbox("Also ask them to accept the consent notice again")
        typed = st.text_input("Type RESET to confirm")
        go = st.form_submit_button("Delete the data", type="primary", use_container_width=True)
    if go:
        chosen = list(labels) if scope == "Every account" else picked
        if not chosen:
            st.error("Choose at least one account.")
        elif typed.strip() != "RESET":
            st.error("Type RESET in capitals to confirm.")
        else:
            try:
                r = server.reset([labels[c] for c in chosen], clear_consent)
                st.session_state.pop("fetched_at", None)                    # reload the data after the reset
                st.session_state["flash"] = ("ok", f"Reset done for {r['accounts']} account(s): removed {r['answers']} answers, {r['concepts']} concepts and {r['notes']} notes.")
                st.rerun()
            except (ServerError, OSError) as e:
                st.error(f"Reset failed: {e}")


def page_pilot() -> None:
    if srv is None and not LIVE_DB.exists():
        return connect_panel()
    if srv is not None and (not LIVE_DB.exists() or time.time() - st.session_state.get("fetched_at", 0) > 120):
        refresh()                                                          # latest data on opening the page, then at most every two minutes
    top = st.columns([5, 1.4], vertical_alignment="bottom")
    top[0].title("Pilot")
    if srv is not None and top[1].button("Refresh", icon=":material/refresh:", use_container_width=True):
        refresh()
        st.rerun()
    msg = st.session_state.pop("flash", None) or flash
    if msg:
        (st.success if msg[0] == "ok" else st.error)(msg[1])
    if not LIVE_DB.exists():
        st.info("No data yet.")
        return
    conn = pilot.open_ro(LIVE_DB)
    try:
        now_ms = int(time.time() * 1000)
        users = pilot.users_table(conn, now_ms)
        stu = users[users["role"] == "student"]
        note(("Live data, loaded " if srv is not None else "Not connected. Showing the copy from ") + ago(time.time() - LIVE_DB.stat().st_mtime) + ". Ten people are too few for significance tests, so everything here is descriptive.")

        st.header("Needs attention")
        items = pilot.attention(conn, now_ms)
        if not items:
            st.markdown('<div class="flag">Nothing needs attention right now.</div>', unsafe_allow_html=True)
        for it in items:
            st.markdown(f'<div class="flag {"warn" if it["level"] == "warn" else ""}">{"<b>Check</b> " if it["level"] == "warn" else ""}{html.escape(it["text"])}</div>', unsafe_allow_html=True)

        st.header("Overview")
        adh = pilot.adherence(conn, now_ms)
        c = st.columns(4)
        c[0].metric("Accounts", len(stu))
        c[1].metric("Accepted consent", int(stu["consented"].sum()))
        c[2].metric("Have answered", int((stu["n_answers"] > 0).sum()))
        c[3].metric("Answers in total", int(stu["n_answers"].sum()))
        if adh["tracked"]:
            note(f"{adh['overdue']} of {adh['tracked']} scheduled concepts are overdue right now; the median overdue concept is {adh['median_days_late']:.1f} days late.")

        st.header("People")
        show_all = st.checkbox("Include the admin account", value=False)
        people = (users if show_all else stu).copy()
        people["last_answer"] = people["days_since_last"].map(lambda d: "never" if pd.isna(d) else ("today" if d < 1 else ("1 day ago" if round(d) == 1 else f"{d:.0f} days ago")))
        st.dataframe(people[["user_id", "username", "consented", "notes", "concepts", "n_answers", "last_answer"]], hide_index=True, width="stretch",
                     column_config={"user_id": "ID", "username": "Account", "consented": st.column_config.CheckboxColumn("Consent"),
                                    "notes": "Notes", "concepts": "Concepts", "n_answers": "Answers", "last_answer": "Last answer"})

        st.header("Participants")
        prof = pilot.profiles_table(conn)
        note("From the sign-up form. Private: only visible here, never shared. Names stay out of every result and write-up.")
        if prof.empty:
            note("Nobody has filled in the form yet.")
        else:
            st.dataframe(prof, hide_index=True, width="stretch",
                         column_config={"username": "Account", "full_name": "Name", "contact": "Contact", "age": "Age", "known_topics": "Already know well"})
            st.download_button("Download as CSV", prof.to_csv(index=False).encode("utf-8"), "participants.csv", "text/csv")

        st.header("Activity")
        da = pilot.daily_activity(conn)
        if da.empty:
            note("No answers yet.")
        else:
            a, b = st.columns(2)
            a.markdown("**Answers per day**")
            a.bar_chart(da.set_index("day")[["answers"]], color=ACCENT, height=230)
            b.markdown("**People who answered each day**")
            b.bar_chart(da.set_index("day")[["active_users"]], color=GREEN, height=230)

        st.header("How the three scheduling methods compare")
        note("Each concept is given one method at random: REMEM (the model), SM-2 (a classic flashcard rule) or a fixed 3-day gap. Students never see which. "
             "This counts review answers only, and with this few people the differences are not meaningful yet.")
        arms = pilot.by_arm(conn).replace({"remem": "REMEM", "sm2": "SM-2", "fixed": "Fixed, every 3 days"})
        st.dataframe(arms, hide_index=True, width="stretch", column_config={
            "arm": "Method", "concepts": "Concepts", "review_answers": "Review answers",
            "accuracy": st.column_config.ProgressColumn("Share correct", format="percent", min_value=0, max_value=1),
            "mean_gap_days": st.column_config.NumberColumn("Average days since last review", format="%.1f")})

        st.header("Are the predictions honest?")
        note("REMEM predicts the chance of a correct answer before each review. If the predicted and the observed values match, the predictions can be trusted.")
        cal = pilot.calibration(conn)
        if cal.empty:
            note("No review answers yet.")
        else:
            a, b = st.columns([1, 1])
            a.dataframe(cal, hide_index=True, width="stretch", column_config={"bin": "Predicted range", "n": "Answers", "predicted": st.column_config.NumberColumn("Predicted", format="%.2f"),
                                                                               "observed": st.column_config.NumberColumn("Observed", format="%.2f")})
            long = cal.melt(id_vars="bin", value_vars=["predicted", "observed"], var_name="kind", value_name="value")
            b.altair_chart(alt.Chart(long).mark_line(point=True).encode(
                x=alt.X("bin:N", title=None, sort=None), y=alt.Y("value:Q", scale=alt.Scale(domain=[0, 1]), title=None),
                color=alt.Color("kind:N", scale=alt.Scale(domain=["predicted", "observed"], range=[ACCENT, AMBER]), legend=alt.Legend(title=None, orient="bottom"))).properties(height=230), width="stretch")

        st.header("Quiz generation")
        h = pilot.llm_health(conn)
        c = st.columns(4)
        c[0].metric("Notes turned into quizzes", f"{h['notes_done']} of {h['notes_total']}")
        c[1].metric("Notes that failed", h["notes_failed"])
        c[2].metric("Questions written", h["questions"])
        c[3].metric("Flagged as bad", f"{h['flagged']}")
        errs = pilot.recent_errors(conn)
        if len(errs):
            st.dataframe(errs, hide_index=True, width="stretch", column_config={"time_ist": "Time (IST)", "title": "Note", "error": "Error"})

        st.header("Final check")
        note("One reserved question per concept, answered without feedback near the end of the pilot. Students only see it while it is open.")
        if srv is None:
            note(f"Currently {'open' if pilot.final_test_open(conn) else 'closed'} (as of the last data copy). Connect to the server to change it.")
        else:
            try:
                is_open = srv.final_open()
            except ServerError as e:
                st.error(str(e))
                is_open = None
            if is_open is not None:
                cols = st.columns([3, 1.4], vertical_alignment="center")
                cols[0].markdown(f"The final check is **{'open' if is_open else 'closed'}**.")
                if cols[1].button("Close it" if is_open else "Open it", use_container_width=True):
                    srv.set_final(not is_open)
                    st.rerun()

            st.header("Reset test data")
        with st.container(border=True, key="danger"):
            st.markdown("### Danger zone")
            note("Use this after you have tried the app with an account and want a clean start. It deletes learning data only; accounts and passwords stay.")
            if srv is None:
                note("Connect to the server to use this.")
            elif st.button("Reset test data...", key="open_reset"):
                reset_dialog(srv)
    finally:
        conn.close()                                              # Windows cannot replace a database file that is still open


# ------------------------------------------------------------------ EdNet results
MODEL_NAMES = {
    "A_bkt_no_forgetting": "A. Knowledge tracing only (no forgetting)", "B_exp_global": "B. Exponential forgetting, one curve for all",
    "C_power_global": "C. Power-law forgetting, one curve for all", "D_power_features(REMEM)": "D. Power-law forgetting with student features (REMEM)",
    "E_exp_features": "E. Exponential forgetting with student features", "D_minus_m": "D without mastery", "D_minus_log_n": "D without practice count",
    "D_minus_ability": "D without student ability", "D_minus_difficulty": "D without question difficulty", "D_minus_rt_z": "D without response time"}


def page_ednet() -> None:
    st.title("EdNet results")
    note("Held-out tests on the public EdNet dataset. Chronological split: the model is fitted on the past and judged on the future. Lower is better for log loss, Brier score and calibration error (ECE).")
    st.header("Baselines")
    b = csv("exp2_baselines.csv")
    if b is not None:
        split = st.radio("Split", ["test", "val"], horizontal=True, key="b_split")
        t = b[b["split"] == split].copy()
        t["model"] = t["model"].replace({"majority": "Always the most common answer", "student_accuracy": "Each student's average", "concept_difficulty": "Each concept's difficulty", "bkt_no_forgetting": "Knowledge tracing (BKT)"})
        st.dataframe(t[["subset", "model", "n", "auc", "logloss", "brier", "ece"]], hide_index=True, width="stretch", column_config={
            "subset": "Rows", "model": "Model", "n": "Answers", "auc": st.column_config.NumberColumn("AUC (higher is better)", format="%.3f"),
            "logloss": st.column_config.NumberColumn("Log loss", format="%.4f"), "brier": st.column_config.NumberColumn("Brier", format="%.4f"), "ece": st.column_config.NumberColumn("ECE", format="%.4f")})
    st.header("Does modelling forgetting help?")
    note("Only answers to a concept the student had already seen. Models A to E differ in how they treat the time since the last practice.")
    m = csv("exp3_forgetting_metrics.csv")
    if m is not None:
        c = st.columns(2)
        split = c[0].radio("Split ", ["test", "val"], horizontal=True)
        subset = c[1].radio("Rows ", ["repeats", "spaced>=1d"], horizontal=True, format_func=lambda s: "All repeats" if s == "repeats" else "Gap of a day or more")
        t = m[(m["split"] == split) & (m["subset"] == subset)].copy().sort_values("logloss")
        t["model"] = t["model"].map(lambda x: MODEL_NAMES.get(x, x))
        st.dataframe(t[["model", "n", "auc", "logloss", "brier", "ece"]], hide_index=True, width="stretch", column_config={
            "model": "Model", "n": "Answers", "auc": st.column_config.NumberColumn("AUC", format="%.3f"), "logloss": st.column_config.NumberColumn("Log loss", format="%.4f"),
            "brier": st.column_config.NumberColumn("Brier", format="%.4f"), "ece": st.column_config.NumberColumn("ECE", format="%.4f")})
        note("Reading: a power-law curve beats an exponential one, but adding student features to it changes very little.")
    cg = csv("exp3_calibration_by_gap.csv")
    if cg is not None:
        st.header("Calibration by time since last practice")
        note("Gap between predicted and observed correctness in each time bucket. Smaller bars are better.")
        cg["model"] = cg["model"].map(lambda x: MODEL_NAMES.get(x, x))
        models = st.multiselect("Models to compare", sorted(cg["model"].unique()), default=sorted(cg["model"].unique())[:3])
        order = ["<5m", "5m-1h", "1h-6h", "6h-1d", "1-3d", "3-7d", "7-14d", "14-30d", "30-90d", ">90d"]
        st.altair_chart(alt.Chart(cg[cg["model"].isin(models)]).mark_bar().encode(
            x=alt.X("bin:N", sort=order, title="Time since last practice"), xOffset="model:N", y=alt.Y("abs_gap:Q", title="Gap between predicted and observed"),
            color=alt.Color("model:N", legend=alt.Legend(title=None, orient="bottom"))).properties(height=300), width="stretch")
    g = csv("exp1_accuracy_by_gap.csv")
    if g is not None:
        st.header("Do people forget over time in this data?")
        note("Share correct by time since the last practice. It falls only slightly, which is why the app starts from a documented prior instead of the fitted curve.")
        st.dataframe(g, hide_index=True, width="stretch", column_config={"bin": "Gap", "n": "Answers", "accuracy": st.column_config.NumberColumn("Share correct", format="%.3f"),
                                                                           "resid_vs_student_mean": st.column_config.NumberColumn("Versus the student's own average", format="%+.3f")})
    exp4_section()
    exp6_section()
    exp7_section()
    exp9_section()
    log = csv("run_log.csv")
    if log is not None:
        with st.expander("Run log (every experiment run, with settings)"):
            st.dataframe(log, hide_index=True, width="stretch")


OFFSET_NAMES = {"G": "Global model only", "G+c": "+ concept offsets", "G+c+s": "+ concept and student offsets", "full": "+ pair offsets (shrunk)", "full_raw": "+ pair offsets (no shrinkage)"}
STRATA_ORDER = ["0 (new pair)", "1-2", "3-5", "6-10", "11-30", "31+"]


def exp4_section() -> None:
    ov, sp = csv("exp4_overall.csv"), csv("exp4_by_sparsity.csv")
    if ov is None or sp is None:
        return
    st.header("Does personalising per concept and student help?")
    note("Offsets nudge the memory strength up or down for a concept, a student, or one student on one concept. A prior pulls each offset toward zero, "
         "so a pair with few answers stays close to the broader average. Lower log loss, Brier and ECE are better. Held-out test split, repeat answers only.")
    t = ov[(ov["split"] == "test") & (ov["subset"] == "repeats")].copy()
    t["model"] = t["model"].map(OFFSET_NAMES)
    st.dataframe(t[["model", "n", "auc", "logloss", "brier", "ece"]], hide_index=True, width="stretch", column_config={
        "model": "Model", "n": "Answers", "auc": st.column_config.NumberColumn("AUC", format="%.3f"), "logloss": st.column_config.NumberColumn("Log loss", format="%.5f"),
        "brier": st.column_config.NumberColumn("Brier", format="%.5f"), "ece": st.column_config.NumberColumn("ECE", format="%.4f")})
    st.markdown("**Log loss by how many earlier answers the student-concept pair had in training**")
    piv = sp.pivot_table(index="stratum", columns="model", values="logloss").reindex(STRATA_ORDER)
    piv = piv[[c for c in OFFSET_NAMES if c in piv.columns]].rename(columns=OFFSET_NAMES).reset_index().rename(columns={"stratum": "Earlier answers on the pair"})
    st.dataframe(piv, hide_index=True, width="stretch")
    summ = csv("exp4_offset_summary.csv")
    note("The gains are small. Offsets help a little at every level, and shrinkage matters little here because the fitted forgetting curve on EdNet is almost flat, "
         "so large changes in memory strength move the predictions only slightly." + (" Offset widths (prior sd) were chosen on validation data; the best student and pair width sat at the largest value tried." if summ is not None else ""))


def exp6_section() -> None:
    tc, sw = csv("exp6_timing_calibration.csv"), csv("exp6_theta_sweep.csv")
    sj = RESULTS / "exp6_summary.json"
    if tc is None or sw is None or not sj.exists():
        return
    names = {"fitted": "EdNet-fitted model", "prior": "Deployed starter prior"}
    st.header("Would the recommended review times be trustworthy?")
    note("For every logged review, REMEM's recommended gap (at the 85% target) is computed from what was known before it. Reviews are then grouped by how the real gap compares with the recommendation, "
         "and the predicted chance of a correct answer is compared with what happened. This is a check of the predictions, not proof that following the schedule helps learning.")
    summ = json.loads(sj.read_text())
    rows = [{"Model": names[k], "Curve shape": v["beta"], "Median recommended gap (days)": v["median_recommended_gap_at_0.85"], "Recommendations at the 180-day limit": v["share_recommendations_at_max_rail"],
             "Reviews within half to double the recommendation": v["n_near_reviews"], "Calibration error there (ECE)": v["near_ece"], "Verdict": v["verdict"]} for k, v in summ.items()]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", column_config={
        "Curve shape": st.column_config.NumberColumn(format="%.3f"), "Median recommended gap (days)": st.column_config.NumberColumn(format="%.1f"),
        "Recommendations at the 180-day limit": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
        "Calibration error there (ECE)": st.column_config.NumberColumn(format="%.3f")})
    tc = tc.assign(model=tc["model"].map(names))
    long = tc.melt(id_vars=["model", "bucket", "n"], value_vars=["predicted", "observed"], var_name="kind", value_name="value")
    order = list(tc["bucket"].drop_duplicates())
    st.altair_chart(alt.Chart(long).mark_bar().encode(
        x=alt.X("bucket:N", sort=order, title="Real gap compared with the recommended gap"), xOffset="kind:N", y=alt.Y("value:Q", scale=alt.Scale(domain=[0, 1]), title="Chance of a correct answer"),
        color=alt.Color("kind:N", scale=alt.Scale(domain=["predicted", "observed"], range=[ACCENT, AMBER]), legend=alt.Legend(title=None, orient="bottom")),
        row=alt.Row("model:N", title=None), tooltip=["model", "bucket", "n", "kind", "value"]).properties(height=200, width=620), width="content")
    st.markdown("**Target retention (θ) sweep**")
    note("A higher target means earlier reviews and more of them. 'Near' counts real reviews within a quarter of the recommended gap.")
    s2 = sw.assign(model=sw["model"].map(names))
    st.dataframe(s2, hide_index=True, width="stretch", column_config={
        "model": "Model", "theta": st.column_config.NumberColumn("Target θ", format="%.2f"), "mean_recommended_days": st.column_config.NumberColumn("Mean recommended gap (days)", format="%.1f"),
        "median_recommended_days": st.column_config.NumberColumn("Median (days)", format="%.1f"), "share_at_max_rail": st.column_config.ProgressColumn("At 180-day limit", format="percent", min_value=0, max_value=1),
        "share_at_min_rail": st.column_config.ProgressColumn("At 1-day limit", format="percent", min_value=0, max_value=1),
        "reviews_per_concept_month": st.column_config.NumberColumn("Reviews per concept per month", format="%.2f"), "n_near_recommendation": "Real reviews near it",
        "predicted_near": st.column_config.NumberColumn("Predicted correct", format="%.2f"), "observed_near": st.column_config.NumberColumn("Observed correct", format="%.2f")})
    note("The fitted EdNet curve is almost flat, so it recommends the maximum gap for most targets and is not usable for scheduling. The starter prior recommends gaps of days to weeks, "
         "but its predictions are not well calibrated for reviews that happen early. The scheduler claim therefore rests on SimLab and the live pilot.")



def _signed(x: float) -> str:
    return f"{x:+.4f}"


def exp7_section() -> None:
    ab = csv("exp7_ablations.csv")
    if ab is None:
        return
    st.header("Which parts of the model matter?")
    note("Each row removes or swaps one part and scores the result on the same held-out repeat answers. "
         "The change is the difference in log loss from the full model, with a 95% interval from resampling students. "
         "A part counts as mattering only when the whole interval is on the worse side of zero. Uncertainty comes from resampling students, not from refitting with other random seeds.")
    t = ab.copy()
    order = {"Reference": 0, "Forgetting": 1, "Forgetting curve": 2, "Features": 3, "Extensions": 4}
    t["_o"] = t["group"].map(order)
    t = t.sort_values(["_o", "logloss"], ascending=[True, True])

    def plain(r):
        if r["group"] == "Reference":
            return "Reference"
        if r["verdict"] == "no demonstrable difference":
            return "No demonstrable difference"
        size = r.get("effect_size", "")
        if r["group"] == "Extensions":
            return ("Helps" if r["verdict"].startswith("better") else "Hurts") + f" ({size})"
        return ("Removing it helps" if r["verdict"].startswith("better") else "The part matters") + f" ({size})"
    t["Result"] = t.apply(plain, axis=1)
    t["Change in log loss"] = t.apply(lambda r: "" if r["group"] == "Reference" else f"{_signed(r['delta_logloss'])}  ({_signed(r['ci_low'])} to {_signed(r['ci_high'])})", axis=1)
    st.dataframe(t[["group", "label", "logloss", "ece", "Change in log loss", "Result"]], hide_index=True, width="stretch", column_config={
        "group": "Kind", "label": "Model", "logloss": st.column_config.NumberColumn("Log loss", format="%.5f"), "ece": st.column_config.NumberColumn("ECE", format="%.4f")})
    note("Positive change = worse than the full model. The size in brackets is a reading aid: under 0.0005 negligible, under 0.002 small, otherwise moderate. "
         "Modelling forgetting and the shape of the curve matter most; each student or concept feature adds almost nothing on its own; the link feature is the largest single gain. "
         "The target-retention trade-off is in the replay section above.")


def exp9_section() -> None:
    sj = RESULTS / "exp9_summary.json"
    ctrl, ov = csv("exp9_controls.csv"), csv("exp9_overall.csv")
    if not sj.exists() or ctrl is None or ov is None:
        return
    s9 = json.loads(sj.read_text())
    g, gs = s9["logloss_gain_overall"], s9["logloss_gain_spaced_1d"]
    st.header("Do recent mistakes on related concepts help?")
    note("A related concept is one that students who struggle with this concept also tend to struggle with (a correlation measured on the training period only). "
         "The feature adds up a student's recent failures on related concepts, fading over time, and the model learns whether that shortens or lengthens memory strength.")
    c = st.columns(3)
    c[0].metric("Gain, all repeats", f"{g['mean_diff']:.4f}", help=f"95% interval {g['lo']:.4f} to {g['hi']:.4f}")
    c[1].metric("Gain, gaps of 1+ day", f"{gs['mean_diff']:.4f}", help=f"95% interval {gs['lo']:.4f} to {gs['hi']:.4f}")
    c[2].metric("With a related failure", f"{s9['share_rows_F_above_0.1']:.0%}")
    note(f"Verdict: <b>{html.escape(s9['verdict'])}</b>. Settings chosen on validation data: {s9['k']} neighbours per concept, fading over {s9['tau_days']:g} day.")
    names = {"repeats": "All repeat answers", "spaced>=1d": "Gap of a day or more", "recent failure elsewhere (F>0.1)": "Recent related failure", "no recent related failure (F<=0.1)": "No recent related failure"}
    o = ov.assign(subset=ov["subset"].map(names))
    st.dataframe(o[["subset", "model", "n", "auc", "logloss", "brier", "ece"]], hide_index=True, width="stretch", column_config={
        "subset": "Answers", "model": "Model", "n": "Count", "auc": st.column_config.NumberColumn("AUC", format="%.3f"), "logloss": st.column_config.NumberColumn("Log loss", format="%.5f"),
        "brier": st.column_config.NumberColumn("Brier", format="%.5f"), "ece": st.column_config.NumberColumn("ECE", format="%.4f")})
    st.markdown("**Is it really about related concepts?**")
    note("Controls build the same feature with the links shuffled across concepts, or with every concept linked equally. "
         "If those gain as much, the feature is only measuring that the student is having a bad stretch.")
    cc = ctrl.copy()
    cc["Gain over the global model"] = cc.apply(lambda r: f"{_signed(r['gain_over_global'])}  ({_signed(r['gain_lo'])} to {_signed(r['gain_hi'])})", axis=1)
    cc["Real links better by"] = cc.apply(lambda r: f"{_signed(r['real_links_better_by'])}  ({_signed(r['better_lo'])} to {_signed(r['better_hi'])})", axis=1)
    st.dataframe(cc[["control", "Gain over the global model", "Real links better by"]], hide_index=True, width="stretch", column_config={"control": "Control"})
    note("About half of the gain also appears with meaningless links, so part of the feature is a general recent-failure signal; the rest depends on which concepts are linked. "
         "EdNet's concepts are numbered tags, so the explanation in the app cannot name related concepts. The feature is not deployed.")



# ------------------------------------------------------------------ SimLab
def page_simlab() -> None:
    st.title("SimLab")
    note("Simulated students whose real memory is known, so any scheduler can be judged against the truth. Results describe simulated learners only.")
    md, fr = csv("exp10_matched.csv"), csv("exp10_frontier.csv")
    if md is None or fr is None:
        st.info("Run `python experiments/exp10_simlab.py` to create these results.")
        return
    st.header("Reviews saved by REMEM")
    note("Each competitor is tuned until it keeps students below 85% recall for the same share of time as REMEM. The table then shows how many fewer reviews REMEM needed. "
         "A negative number means REMEM needed more. Differences smaller than the spread between runs are not shown to be real.")
    t = md[md["matched_on"] == "below_target"].groupby(["gen", "phi", "baseline"]).agg(mean=("reviews_saved_pct", "mean"), lowest=("reviews_saved_pct", "min"), highest=("reviews_saved_pct", "max")).round(1).reset_index()
    t["gen"] = t["gen"].map({"gen1": "Power-law (matches REMEM)", "gen2": "Exponential (mismatched)", "gen3": "Two-speed mixture (mismatched)"})
    t["baseline"] = t["baseline"].map({"fixed": "Best fixed gap", "sm2": "SM-2"})
    st.dataframe(t, hide_index=True, width="stretch", column_config={
        "gen": "True forgetting curve", "phi": st.column_config.NumberColumn("Strength of spacing effect", format="%.1f"), "baseline": "Compared with",
        "mean": st.column_config.NumberColumn("Reviews saved, average %", format="%.1f"), "lowest": st.column_config.NumberColumn("Lowest run %", format="%.1f"), "highest": st.column_config.NumberColumn("Highest run %", format="%.1f")})
    st.header("Reviews against coverage")
    note("Further left and lower is better: fewer reviews and less time below the 85% recall target.")
    c = st.columns(2)
    gen = c[0].radio("True forgetting curve", ["gen1", "gen2", "gen3"], horizontal=True, format_func=lambda g: {"gen1": "Power-law", "gen2": "Exponential", "gen3": "Mixture"}[g])
    phi = c[1].radio("Spacing effect", sorted(fr["phi"].unique()), index=1, horizontal=True)
    f = fr[(fr["gen"] == gen) & (fr["phi"] == phi)].groupby(["policy", "knob"], as_index=False).mean(numeric_only=True)
    f["policy"] = f["policy"].map({"remem": "REMEM", "remem_global": "REMEM, one shared curve", "remem_prior": "REMEM, starter prior", "fixed": "Fixed gap", "sm2": "SM-2"})
    st.altair_chart(alt.Chart(f).mark_line(point=True).encode(
        x=alt.X("reviews_per_concept:Q", title="Reviews per concept in 60 days"), y=alt.Y("frac_below_target:Q", title="Share of time below 85% recall"),
        color=alt.Color("policy:N", legend=alt.Legend(title=None, orient="bottom")), tooltip=["policy", "knob", "reviews_per_concept", "frac_below_target", "final_recall"]).properties(height=340), width="stretch")
    rc = csv("exp10_recovery.csv")
    if rc is not None:
        st.header("Can the model recover each student's true memory strength?")
        note("A rank correlation near 1 would mean yes. Values near zero mean the personalised estimates did not track the truth here.")
        r = rc.groupby(["gen", "phi"])[["spearman_S", "beta_fit"]].mean().round(2).reset_index()
        r["gen"] = r["gen"].map({"gen1": "Power-law", "gen2": "Exponential", "gen3": "Mixture"})
        st.dataframe(r, hide_index=True, width="stretch", column_config={"gen": "True curve", "phi": "Spacing effect", "spearman_S": "Rank correlation", "beta_fit": "Fitted curve shape"})


# ------------------------------------------------------------------ deployed model
def page_model() -> None:
    st.title("Model")
    note("The forgetting curve the app uses today. It is a documented starting prior because the EdNet fit is almost flat.")
    p = ARTIFACTS / "stability_model.json"
    if not p.exists():
        st.info("No model file found.")
        return
    sm = json.loads(p.read_text())
    beta = float(sm.get("beta", 0.5))
    k = 0.9 ** (-1 / beta) - 1
    S = st.slider("Memory strength (days until recall drops to 90%)", 1.0, 60.0, 8.0)
    days = list(range(0, 61))
    df = pd.DataFrame({"day": days, "recall": [(1 + k * d / S) ** (-beta) for d in days]})
    st.altair_chart(alt.Chart(df).mark_area(opacity=0.12, color=ACCENT, line={"color": ACCENT, "strokeWidth": 3}).encode(
        x=alt.X("day:Q", title="Days since last practice"), y=alt.Y("recall:Q", scale=alt.Scale(domain=[0, 1]), title="Chance of recalling")).properties(height=320), width="stretch")
    st.markdown("Recall after *t* days is (1 + k·t/S)^(−β), with k chosen so that recall equals 90% when *t* = S.")
    names = {"m": "Mastery", "log_n": "Practice count (log)", "ability": "Student ability", "difficulty": "Question difficulty", "rt_z": "Response time"}
    coef = pd.DataFrame({"Factor": ["Baseline"] + [names.get(f, f) for f in sm["features"]], "Weight": [round(float(w), 3) for w in sm["w"][:len(sm["features"]) + 1]]})
    st.dataframe(coef, hide_index=True, width="stretch")
    note(f"Curve shape β = {beta:g}. Memory strength is exp(baseline + the weighted factors).")


def findings_rows() -> list[dict]:
    """One row per research question, built from the logged result files so the numbers cannot drift from the experiments."""
    rows = []
    g = csv("exp1_accuracy_by_gap.csv")
    if g is not None:
        rows.append({"Question": "Does time since the last practice carry a forgetting signal in the data?",
                     "What we found": f"Accuracy falls from {g['accuracy'].iloc[0]:.1%} (under 5 minutes) to {g['accuracy'].iloc[-2]:.1%} (30 to 90 days); relative to each student's own average the drop is about {abs(g['resid_vs_student_mean'].iloc[0] - g['resid_vs_student_mean'].iloc[-2]) * 100:.0f} points.",
                     "Verdict": "Partly supported", "Why not stronger": "Real but small, and students choose when to revisit, so the data cannot prove cause.", "Details": "EdNet results"})
    b = csv("exp2_baselines.csv")
    if b is not None:
        t = b[(b["split"] == "test") & (b["subset"] == "all")].set_index("model")
        rows.append({"Question": "Does the knowledge-tracing layer work?",
                     "What we found": f"AUC {t.loc['bkt_no_forgetting', 'auc']:.3f} against {t.loc['majority', 'auc']:.3f} for always guessing the common answer and {t.loc['student_accuracy', 'auc']:.3f} for each student's average; best log loss of the four.",
                     "Verdict": "Supported", "Why not stronger": "A modest absolute level of prediction, as expected for one-skill models.", "Details": "EdNet results"})
    a = csv("exp7_ablations.csv")
    if a is not None:
        a = a.set_index("model")
        rows.append({"Question": "H1: Does modelling forgetting, and a student-aware stability, help?",
                     "What we found": f"Removing the forgetting term costs {a.loc['A', 'delta_logloss']:.4f} log loss, using an exponential instead of a power-law curve costs {a.loc['B', 'delta_logloss']:.4f}; the student and concept features add only {a.loc['C', 'delta_logloss']:.4f} together.",
                     "Verdict": "Supported (small)", "Why not stronger": "The curve shape matters; the individual features are negligible on EdNet.", "Details": "EdNet results"})
    o, sp = csv("exp4_overall.csv"), csv("exp4_by_sparsity.csv")
    if o is not None and sp is not None:
        t = o[(o["split"] == "test") & (o["subset"] == "repeats")].set_index("model")
        sparse = sp[sp["stratum"].isin(["1-2", "3-5", "6-10"])].pivot_table(index="stratum", columns="model", values="logloss")
        better = int((sparse["full"] < sparse["full_raw"]).sum())
        rows.append({"Question": "H2: Do per-concept and per-student offsets help, especially for pairs with few answers?",
                     "What we found": f"Log loss improves by {t.loc['G', 'logloss'] - t.loc['full', 'logloss']:.4f} overall; shrinking beats unshrunk pair fitting in {better} of 3 sparse groups, by tiny margins.",
                     "Verdict": "Weakly supported", "Why not stronger": "Gains are small and validation preferred almost no shrinkage; not deployed.", "Details": "EdNet results"})
    sj = RESULTS / "exp9_summary.json"
    if sj.exists():
        s9 = json.loads(sj.read_text())
        rows.append({"Question": "H4: Does a recent failure on a related concept predict forgetting?",
                     "What we found": f"Log loss improves by {s9['logloss_gain_overall']['mean_diff']:.4f} (95% interval {s9['logloss_gain_overall']['lo']:.4f} to {s9['logloss_gain_overall']['hi']:.4f}); shuffled-link controls gain about half as much.",
                     "Verdict": "Supported (small)" if s9["logloss_gain_overall"]["lo"] > 0 else "Not demonstrated",
                     "Why not stronger": "About half the gain is a general recent-failure signal; concepts are numbered tags, so it cannot be explained to a student.", "Details": "EdNet results"})
    if a is not None and "D+F+offsets" in a.index:
        rows.append({"Question": "Does combining the validated extensions give the best offline model?",
                     "What we found": f"Link feature plus offsets together improve log loss by {-a.loc['D+F+offsets', 'delta_logloss']:.4f} over the full model and cut calibration error from {a.loc['D', 'ece']:.3f} to {a.loc['D+F+offsets', 'ece']:.3f}.",
                     "Verdict": "Supported (moderate)" if a.loc["D+F+offsets", "ci_high"] < 0 else "Not demonstrated",
                     "Why not stronger": "Still a small absolute gain on EdNet; not deployed because the app's concepts have no co-error data.", "Details": "EdNet results"})
    m = csv("exp10_matched.csv")
    if m is not None:
        mm = m[(m["matched_on"] == "below_target") & (m["phi"] == 1.5)].groupby("baseline")["reviews_saved_pct"].mean()
        rec = csv("exp10_recovery.csv")
        rows.append({"Question": "H3 / RQ4: Does threshold scheduling need fewer reviews than SM-2 or a fixed interval at the same coverage?",
                     "What we found": f"In simulated students with known memory it needs {mm['sm2']:.0f}% fewer reviews than SM-2 and {abs(mm['fixed']):.0f}% {'fewer' if mm['fixed'] > 0 else 'more'} than the best fixed interval (tuned with the truth); this holds when the true curve differs from the model's.",
                     "Verdict": "Partly supported", "Why not stronger": "It matches a tuned fixed interval rather than beating it, and personalised estimates did not track the true memory strength (rank correlation near zero).", "Details": "SimLab"})
    s6 = RESULTS / "exp6_summary.json"
    if s6.exists():
        j = json.loads(s6.read_text())["prior"]
        rows.append({"Question": "Are the recommended review times trustworthy on real logs?",
                     "What we found": f"The deployed starter curve recommends a median gap of {j['median_recommended_gap_at_0.85']:.0f} days; near those gaps its predicted chance of a correct answer is off by {j['near_ece']:.2f} (limit 0.05).",
                     "Verdict": "Not supported on EdNet" if j["verdict"] == "unreliable" else "Supported", "Why not stronger": "EdNet is English test practice, not study notes; the pilot measures this on real study material.", "Details": "EdNet results"})
    rows.append({"Question": "Pilot: is predicted recall calibrated on real study material, and how do the three schedulers compare?",
                 "What we found": "Collecting data now (about 14 days, up to 10 people). Calibration comes first; the arm comparison and the delayed test are descriptive only.",
                 "Verdict": "Pending", "Why not stronger": "Too few people for significance tests by design.", "Details": "Pilot"})
    return rows


def page_findings() -> None:
    st.title("Findings")
    note("What the project set out to answer, what the evidence shows so far, and how strong it is. Every number is read from the logged result files.")
    rows = findings_rows()
    if not rows:
        st.info("No results found. Run the experiments first (see the README).")
        return
    def tone(v: str) -> str:
        return GREEN if v.startswith("Supported") else RED if v.startswith("Not supported") else "#545c7c" if v == "Pending" else AMBER
    for r in rows:
        st.markdown(f'<div class="finding"><div class="fq">{html.escape(r["Question"])}</div>'
                    f'<div class="fv" style="color:{tone(r["Verdict"])}">{html.escape(r["Verdict"])}</div>'
                    f'<p>{html.escape(r["What we found"])}</p>'
                    f'<p class="note">{html.escape(r["Why not stronger"])} Details: {html.escape(r["Details"])}.</p></div>', unsafe_allow_html=True)
    st.header("In one paragraph")
    st.markdown("REMEM is a working, deployed revision scheduler whose parts are interpretable and tested. On public data the knowledge-tracing layer and a power-law forgetting term help, "
                "but the gains from personalising per student or concept are small, and the data is too flat to learn a usable forgetting curve, so the app starts from a documented prior. "
                "In simulation, threshold scheduling matches the best tuned fixed interval and needs far fewer reviews than SM-2. Whether it helps real students is what the pilot is for; "
                "nothing here claims that it improves learning.")



pages = [
    st.Page(page_pilot, title="Pilot", icon=":material/groups:", url_path="pilot", default=True),
    st.Page(page_findings, title="Findings", icon=":material/fact_check:", url_path="findings"),
    st.Page(page_ednet, title="EdNet results", icon=":material/science:", url_path="ednet"),
    st.Page(page_simlab, title="SimLab", icon=":material/model_training:", url_path="simlab"),
    st.Page(page_model, title="Model", icon=":material/show_chart:", url_path="model"),
]
nav = st.navigation(pages, position="sidebar")
with st.sidebar:
    if srv is not None:
        host = srv.base.split("://")[-1]
        st.markdown(f'<div class="conn"><span class="dot"></span>Connected<br><span>{html.escape(host)}</span></div>', unsafe_allow_html=True)
        if st.button("Disconnect", key="disconnect", type="tertiary", icon=":material/logout:"):
            st.session_state.pop("srv", None)
            st.session_state["auto_failed"] = "Disconnected."
            st.rerun()
    else:
        st.markdown('<div class="conn"><span class="dot off"></span>Not connected</div>', unsafe_allow_html=True)
nav.run()
