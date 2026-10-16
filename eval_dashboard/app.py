from pathlib import Path
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"

st.set_page_config(
    page_title="REMEM | Learning Analytics",
    page_icon="R",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------- STYLING ----------

st.markdown("""
<style>
    .stApp {
        background-color: #f5f7fa;
    }

    .block-container {
        padding-top: 2rem;
        padding-bottom: 3rem;
        max-width: 1450px;
    }

    header[data-testid="stHeader"] {
        background-color: transparent;
    }

    [data-testid="stSidebar"] {
        background-color: #101c2c;
    }

    [data-testid="stSidebar"] * {
        color: #f3f6fa;
    }

    .brand {
        font-size: 2.35rem;
        font-weight: 800;
        letter-spacing: -1.5px;
        color: #14243a;
        margin-bottom: 0;
    }

    .brand span {
        color: #d5a900;
    }

    .subtitle {
        color: #667085;
        font-size: 1rem;
        margin-top: 0.15rem;
        margin-bottom: 1.5rem;
    }

    .section-title {
        color: #14243a;
        font-size: 1.3rem;
        font-weight: 700;
        margin-top: 1.1rem;
        margin-bottom: 0.2rem;
    }

    .section-caption {
        color: #667085;
        font-size: 0.9rem;
        margin-bottom: 1rem;
    }

    .prototype-warning {
        background: #fff1f0;
        border: 1px solid #e5484d;
        border-left: 6px solid #c62828;
        border-radius: 8px;
        padding: 16px 20px;
        margin: 1rem 0 1.5rem 0;
        color: #7f1d1d;
    }

    .prototype-warning strong {
        color: #991b1b;
        font-size: 1rem;
    }

    .prototype-warning p {
        margin: 5px 0 0 0;
        font-size: 0.9rem;
        line-height: 1.5;
    }

    .metric-card {
        background: #ffffff;
        border: 1px solid #e4e8ef;
        border-radius: 12px;
        padding: 20px;
        min-height: 120px;
        box-shadow: 0 2px 8px rgba(16, 28, 44, 0.035);
    }

    .metric-label {
        color: #667085;
        font-size: 0.85rem;
        font-weight: 600;
        margin-bottom: 10px;
    }

    .metric-value {
        color: #14243a;
        font-size: 1.85rem;
        font-weight: 750;
        line-height: 1.2;
    }

    .metric-note {
        color: #667085;
        font-size: 0.78rem;
        margin-top: 8px;
    }

    .info-box {
        background: #ffffff;
        border: 1px solid #e4e8ef;
        border-radius: 10px;
        padding: 16px 18px;
        margin: 1rem 0;
    }

    .footer {
        border-top: 1px solid #e4e8ef;
        padding-top: 15px;
        margin-top: 2rem;
        color: #667085;
        font-size: 0.8rem;
    }

    div[data-testid="stDataFrame"] {
        border: 1px solid #e4e8ef;
        border-radius: 8px;
        overflow: hidden;
    }

    .stButton button {
        background-color: #d5a900;
        color: #14243a;
        border: none;
        border-radius: 7px;
        font-weight: 650;
    }

    .stButton button:hover {
        background-color: #edc52b;
        color: #14243a;
        border: none;
    }
</style>
""", unsafe_allow_html=True)


# ---------- DATA ----------

mastery_path = DATA / "mastery_scores.csv"
schedule_path = DATA / "revision_schedule.csv"

st.sidebar.markdown(
    '<div style="font-size:1.8rem;font-weight:800;">REMEM<span '
    'style="color:#edc52b;">.</span></div>',
    unsafe_allow_html=True,
)
st.sidebar.caption("Learning analytics prototype")
st.sidebar.divider()

st.sidebar.markdown("### Navigation")
st.sidebar.markdown("**01**  Learner overview")
st.sidebar.markdown("**02**  Revision priorities")
st.sidebar.markdown("**03**  Mastery analysis")

st.sidebar.divider()
st.sidebar.caption("Research build · v0.1")

if not mastery_path.exists() or not schedule_path.exists():
    st.error(
        "Required data files are missing. Run the mastery estimator "
        "and revision scheduler first."
    )
    st.stop()

mastery = pd.read_csv(mastery_path)
schedule = pd.read_csv(schedule_path)

students = sorted(mastery["student_id"].astype(str).unique())

# ---------- HEADER ----------

st.markdown(
    '<div class="brand">REMEM<span>.</span></div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="subtitle">'
    'Personalised Learning Analytics & Revision Planning'
    '</div>',
    unsafe_allow_html=True,
)

# ---------- PROTOTYPE DISCLOSURE ----------

st.markdown("""
<div class="prototype-warning">
    <strong>⚠ RESEARCH PROTOTYPE · LIMITED DATASET</strong>
    <p>
        This demonstration uses a processed subset of the larger EdNet
        educational dataset: 30,811 learning interactions from 100 learners.
        Results are exploratory and may not generalise to other learners.
        Mastery is estimated from historical answer accuracy, while revision
        priorities use a heuristic scoring method. A trained BKT model and
        validated forgetting-curve predictions are not currently active.
        This system is not intended for real-world learning decisions.
    </p>
</div>
""", unsafe_allow_html=True)

# ---------- LEARNER SELECTION ----------

st.markdown(
    '<div class="section-title">Learner overview</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="section-caption">'
    'Explore historical interaction data for an example learner.'
    '</div>',
    unsafe_allow_html=True,
)

selected_student = st.selectbox(
    "Select demonstration learner",
    students,
    format_func=lambda x: f"Learner {x}",
)

learner = mastery[
    mastery["student_id"].astype(str) == selected_student
].copy()

plan = schedule[
    schedule["student_id"].astype(str) == selected_student
].copy()

plan = plan.sort_values("priority_score", ascending=False)

if learner.empty:
    st.warning("No mastery records are available for this learner.")
    st.stop()

# ---------- METRICS ----------

average_accuracy = learner["mastery_score"].mean()
question_count = len(learner)
revision_count = int((plan["priority_score"] >= 50).sum())

c1, c2, c3 = st.columns(3)

with c1:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">QUESTIONS OBSERVED</div>
        <div class="metric-value">{question_count:,}</div>
        <div class="metric-note">Unique learner-question pairs</div>
    </div>
    """, unsafe_allow_html=True)

with c2:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">AVERAGE HISTORICAL ACCURACY</div>
        <div class="metric-value">{average_accuracy:.1f}%</div>
        <div class="metric-note">Based on recorded answers</div>
    </div>
    """, unsafe_allow_html=True)

with c3:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">HIGH-PRIORITY ITEMS</div>
        <div class="metric-value">{revision_count:,}</div>
        <div class="metric-note">Priority score of 50 or above</div>
    </div>
    """, unsafe_allow_html=True)

# ---------- REVISION PLAN ----------

st.markdown("---")
st.markdown(
    '<div class="section-title">Recommended revision plan</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="section-caption">'
    'Questions are ranked by estimated revision priority. '
    'Higher scores indicate greater urgency under the current heuristic.'
    '</div>',
    unsafe_allow_html=True,
)

if plan.empty:
    st.info("No revision recommendations are available.")
else:
    display_plan = plan[[
        "question_id",
        "mastery",
        "attempts",
        "days_since_review",
        "priority_score",
        "recommended_action",
    ]].head(20).copy()

    display_plan["mastery"] = (
        display_plan["mastery"] * 100
    ).round(1)

    display_plan["days_since_review"] = (
        display_plan["days_since_review"]
    ).round(1)

    display_plan["priority_score"] = (
        display_plan["priority_score"]
    ).round(1)

    display_plan.columns = [
        "Question ID",
        "Historical Accuracy (%)",
        "Attempts",
        "Days Since Attempt",
        "Priority Score",
        "Suggested Action",
    ]

    st.dataframe(
        display_plan,
        use_container_width=True,
        hide_index=True,
        height=430,
    )

    st.download_button(
        "Export revision plan",
        data=plan.to_csv(index=False).encode("utf-8"),
        file_name=f"remem_revision_{selected_student}.csv",
        mime="text/csv",
    )

# ---------- MASTERY ANALYSIS ----------

st.markdown("---")
st.markdown(
    '<div class="section-title">Mastery distribution</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="section-caption">'
    'Historical accuracy across questions attempted by the selected learner.'
    '</div>',
    unsafe_allow_html=True,
)

left, right = st.columns([1.4, 1])

with left:
    bins = pd.cut(
        learner["mastery_score"],
        bins=[-0.1, 49.9, 79.9, 100],
        labels=["Below 50%", "50–79%", "80–100%"],
    )

    distribution = (
        bins.value_counts(sort=False)
        .reindex(["Below 50%", "50–79%", "80–100%"], fill_value=0)
    )

    chart_data = pd.DataFrame({
        "Accuracy range": distribution.index.astype(str),
        "Number of questions": distribution.values,
    }).set_index("Accuracy range")

    st.bar_chart(chart_data)

with right:
    st.markdown("""
    <div class="info-box">
        <strong style="color:#14243a;">How to interpret this</strong>
        <p style="color:#667085;font-size:0.9rem;">
            <b>Below 50%:</b> Consider revisiting the material.<br><br>
            <b>50–79%:</b> Additional practice may help.<br><br>
            <b>80–100%:</b> Consider a brief review to reinforce learning.
        </p>
    </div>
    """, unsafe_allow_html=True)

# ---------- EVALUATION ----------

st.markdown("---")
st.markdown(
    '<div class="section-title">Evaluation & Dataset Analysis</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="section-caption">'
    'Descriptive analysis of the processed EdNet interaction subset.'
    '</div>',
    unsafe_allow_html=True,
)

raw_path = DATA / "ednet_clean.csv"

if raw_path.exists():
    interactions = pd.read_csv(raw_path)

    interactions["correct"] = pd.to_numeric(
        interactions["correct"], errors="coerce"
    )
    interactions = interactions.dropna(subset=["correct"])

    total = len(interactions)
    correct_count = int(interactions["correct"].sum())
    incorrect_count = total - correct_count
    overall_accuracy = (
        correct_count / total * 100 if total else 0
    )

    a, b, c = st.columns(3)

    with a:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">TOTAL INTERACTIONS</div>
            <div class="metric-value">{total:,}</div>
            <div class="metric-note">Processed interaction records</div>
        </div>
        """, unsafe_allow_html=True)

    with b:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">CORRECT RESPONSES</div>
            <div class="metric-value">{correct_count:,}</div>
            <div class="metric-note">Recorded correct answers</div>
        </div>
        """, unsafe_allow_html=True)

    with c:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">OVERALL ACCURACY</div>
            <div class="metric-value">{overall_accuracy:.1f}%</div>
            <div class="metric-note">Descriptive dataset statistic</div>
        </div>
        """, unsafe_allow_html=True)

    left, right = st.columns(2)

    with left:
        st.markdown("#### Response distribution")

        response_chart = pd.DataFrame({
            "Response": ["Correct", "Incorrect"],
            "Interactions": [correct_count, incorrect_count],
        }).set_index("Response")

        st.bar_chart(response_chart)

    with right:
        st.markdown("#### Revision priority distribution")

        priority_bins = pd.cut(
            schedule["priority_score"],
            bins=[-0.1, 33.33, 66.67, 100],
            labels=["Low", "Medium", "High"],
        )

        priority_counts = (
            priority_bins.value_counts(sort=False)
            .reindex(["Low", "Medium", "High"], fill_value=0)
        )

        priority_chart = pd.DataFrame({
            "Priority": priority_counts.index.astype(str),
            "Questions": priority_counts.values,
        }).set_index("Priority")

        st.bar_chart(priority_chart)

    st.markdown("#### Methodology and limitations")

    st.markdown("""
    <div class="prototype-warning">
        <strong>INTERPRET RESULTS WITH CAUTION</strong>
        <p>
            <b>Dataset:</b> A processed subset of EdNet containing 30,811
            interactions from 100 learners, selected from a much larger dataset.
            <br><br>
            <b>Mastery estimation:</b> Historical correctness is used to
            calculate empirical accuracy for each learner-question pair.
            This is not a calibrated probability of knowledge mastery.
            <br><br>
            <b>Revision scheduling:</b> A heuristic combines historical
            accuracy and elapsed time since an attempt. The elapsed time
            reflects the age of the historical dataset and should not be
            interpreted as a real learner's current revision interval.
            <br><br>
            <b>Model status:</b> BKT training did not complete successfully.
            No BKT-based performance improvement or predictive accuracy
            is claimed.
            <br><br>
            <b>Evaluation status:</b> The displayed statistics are descriptive.
            A held-out test set, baseline comparison, and validated learning
            outcome evaluation remain future work.
        </p>
    </div>
    """, unsafe_allow_html=True)

else:
    st.warning(
        "The processed interaction file is missing. "
        "Dataset evaluation cannot be displayed."
    )
# ---------- FOOTER ----------

st.markdown("""
<div class="footer">
    REMEM · Academic project prototype · v0.1<br>
    Data source: EdNet · Metrics and recommendations are experimental.
</div>
""", unsafe_allow_html=True)