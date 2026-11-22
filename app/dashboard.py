"""
HRL RAG chunking experiment - read-only Streamlit dashboard.

    .venv/bin/streamlit run app/dashboard.py        ->  http://127.0.0.1:8501

Reads results/<run-id>/ folders (original results + optional rescored_v2.*), the ground truth, the v2
scoring revisions and reviewer failure-analysis files. No AWS SDK is imported and no network calls are made.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
from results_loader import ARMS, GROUND_TRUTH, discover_runs, fmt, load_ground_truth, summarize_run  # noqa: E402

st.set_page_config(page_title="HRL RAG chunking experiment", page_icon=":bar_chart:", layout="wide")

ARM_LABELS = [v["label"] for v in ARMS.values()]
ARM_COLORS = [v["color"] for v in ARMS.values()]
COLOR = alt.Color("Strategy:N", scale=alt.Scale(domain=ARM_LABELS, range=ARM_COLORS),
                  legend=alt.Legend(orient="top", direction="vertical", title=None, labelLimit=0))
LEXICAL_NOTE = ("**Lexical scores are not semantically verified.** Keyword, passage-evidence and cited-chunk scores "
                "(original v1 and revised v2) use string/token matching only - no human review and no LLM judge. "
                "Semantic judgments appear only in the clearly labeled *reviewer reading* column.")
REVISIONS_PATH = GROUND_TRUTH.parent / "scoring_revisions.json"


@st.cache_data(ttl=10)
def get_runs():
    return discover_runs()


@st.cache_data
def get_gt():
    return load_ground_truth()


@st.cache_data
def get_revisions():
    return json.loads(REVISIONS_PATH.read_text()) if REVISIONS_PATH.is_file() else {}


def hbars(df: pd.DataFrame, value_title: str, fmt_str: str, domain_max=None):
    """Horizontal grouped bars: metric names on the y-axis (never clipped), one measure family per chart."""
    x_scale = alt.Scale(domain=[0, domain_max]) if domain_max else alt.Scale(zero=True, nice=True)
    base = alt.Chart(df).encode(
        y=alt.Y("Metric:N", title=None, sort=list(dict.fromkeys(df["Metric"])), axis=alt.Axis(labelLimit=0)),
        yOffset=alt.YOffset("Strategy:N", sort=ARM_LABELS),
        x=alt.X("Value:Q", title=value_title, scale=x_scale, axis=alt.Axis(grid=True, gridOpacity=0.35)),
        color=COLOR,
        tooltip=[alt.Tooltip("Strategy:N"), alt.Tooltip("Metric:N"), alt.Tooltip("Value:Q", format=fmt_str)],
    )
    bars = base.mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
    labels = base.mark_text(align="left", dx=4, fontSize=11, color="#52514e").encode(text=alt.Text("Value:Q", format=fmt_str))
    # Step sizing: every (metric, strategy) bar gets 18px, so small charts cannot collapse or overlap.
    return (bars + labels).properties(height=alt.Step(18))


def long_df(rows_by_arm: dict, metrics: dict[str, str]) -> tuple[pd.DataFrame, list[str]]:
    rows, missing = [], []
    for key, label in metrics.items():
        for arm, s in rows_by_arm.items():
            if s.get(key) is None:
                missing.append(f"{label} ({ARMS[arm]['label']})")
            else:
                rows.append({"Metric": label, "Strategy": ARMS[arm]["label"], "Value": float(s[key])})
    return pd.DataFrame(rows), missing


def chart_block(title: str, df: pd.DataFrame, missing: list[str], value_title: str, fmt_str: str, domain_max=None):
    st.markdown(f"**{title}**")
    if not df.empty:
        st.altair_chart(hbars(df, value_title, fmt_str, domain_max), use_container_width=True)
    if missing:
        st.caption("N/A (not available for this run): " + "; ".join(missing))


# ------------------------------------------------------------------ header and sidebar
st.title("HRL RAG chunking experiment")
st.caption("Fixed-size (100-token) vs hierarchical (1500/300-token) chunking - Bedrock Knowledge Bases + Amazon Nova Micro")
st.info("**Read-only dashboard.** Reads local `results/` files, the ground truth, scoring revisions and reviewer notes. "
        "It makes no AWS API calls and invokes no models.", icon=":material/lock:")

runs = get_runs()
if not runs:
    st.warning("No evaluation runs found under `results/`. Run `scripts/run_evaluation.py` first.")
    st.stop()
gt, revisions = get_gt(), get_revisions()

with st.sidebar:
    st.header("Run")
    labels = {r.run_id: f"{r.run_id} · {len(r.question_ids)} question(s)"
                        + (" · LEGACY metrics" if r.schema != "current" else "")
                        + (" · v2 rescored" if r.has_v2 else "") for r in runs}
    run_id = st.selectbox("Evaluation run (newest first)", list(labels), format_func=labels.get)
    run = next(r for r in runs if r.run_id == run_id)
    st.header("Question")
    wanted = st.query_params.get("q")             # e.g. ?q=Q30 to link/capture a specific question
    qid = st.selectbox("Question", run.question_ids,
                       index=run.question_ids.index(wanted) if wanted in run.question_ids else 0,
                       format_func=lambda q: f"{q} - {gt[q]['question'][:60]}..." if q in gt else q)
    st.divider()
    st.caption(f"Model: `{run.meta.get('model', 'N/A')}`  \nInference config: `{run.meta.get('inference_config', 'N/A')}`  \n"
               f"Top-k: `{run.meta.get('top_k', 'N/A')}` · prompt `{run.meta.get('prompt_template_version', 'N/A')}`  \n"
               f"Config fingerprint: `{run.meta.get('config_fingerprint', 'N/A')}`  \n"
               f"Revised scoring: `{run.v2_meta.get('scoring_version', 'not computed')}`"
               + (f" (revisions `{run.v2_meta.get('revisions_sha256')}`)" if run.has_v2 else "")
               + f"  \nFolder: `{run.path.parent.name}/{run.path.name}`")
    if st.button("Rescan results folder"):
        get_runs.clear()
        st.rerun()

if run.schema != "current":
    st.warning("**Legacy metrics.** This run was recorded before the metric fix: passage-evidence coverage and cited-chunk "
               "keyword support were not recorded and are shown as **N/A**; its page metric is the informational page-label "
               "hit; citation validity means citation **ID** validity only.", icon=":material/history:")
if not run.has_v2:
    st.caption("Revised (v2) scores: not computed for this run - run `scripts/rescore_results.py`. Shown as N/A.")
st.caption(LEXICAL_NOTE)

# ------------------------------------------------------------------ run summary (original v1 metrics)
summary = summarize_run(run)
st.subheader(f"Run summary - {len(run.question_ids)} question(s)")
for arm, s in summary.items():
    lab, color = ARMS[arm]["label"], ARMS[arm]["color"]
    v2s = run.v2_summary.get(arm, {})
    head, a, b, c, d, e = st.columns([1.6, 1, 1, 1, 1, 1])
    head.markdown(f"<div style='border-left:6px solid {color};padding:6px 0 0 8px;font-weight:600'>{lab}</div>",
                  unsafe_allow_html=True)
    a.metric("Correct - v1", fmt(s["fully_correct"], "pct"), help="Original v1: all ground-truth facts string-matched")
    b.metric("Correct - v2", fmt(v2s.get("v2_all_required_facts_matched"), "pct"),
             help="Revised v2: all required facts token-matched (formatting-tolerant); lexical, not semantic")
    c.metric("Passage evidence", fmt(s["passage_evidence_coverage"], "pct"), help="Token match, same document")
    d.metric("Input tokens", fmt(s["input_tokens"], "int"))
    e.metric("Cost (USD)", "N/A" if s["cost_usd"] is None else f"${s['cost_usd']:.4f}", help=fmt(s["cost_usd"], "usd"))

c1, c2 = st.columns(2)
with c1:
    df, miss = long_df(summary, {"fully_correct": "All facts matched (v1)", "answer_keyword_coverage": "Answer fact coverage (v1)",
                                 "keyword_recall": "Retrieval fact recall", "passage_evidence_coverage": "Passage evidence",
                                 "all_passages_present": "All passages present", "cited_chunk_keyword_support": "Cited-chunk support (v1)"})
    chart_block("Quality scores - original v1 (0-1, lexical)", df, miss, "Score (0-1)", ".2f", domain_max=1.15)
with c2:
    df, miss = long_df(summary, {"input_tokens": "Input tokens", "output_tokens": "Output tokens"})
    chart_block("Tokens (sum over questions)", df, miss, "Tokens", ",.0f")
    df, miss = long_df(summary, {"retrieve_ms": "Retrieve", "generate_ms": "Generate (service)"})
    chart_block("Latency (mean ms per question)", df, miss, "Milliseconds", ",.0f")
    df, miss = long_df(summary, {"cost_usd": "Generation cost"})
    chart_block("Estimated cost (USD)", df, miss, "USD", "$.6f")

# ------------------------------------------------------------------ original vs revised scoring
st.divider()
st.subheader("Original (v1) vs revised (v2) answer scoring")
st.caption("v2 tolerates hyphen/spacing/thousands-separator/unit-plural formatting but rejects different numbers or "
           "identifiers, parses citations such as `[S1, Section 9]`, and scores Q30/Q31 on the facts the question "
           "actually asks for (`data/evaluation/scoring_revisions.json`). Both versions are lexical. Original files are unchanged.")
if run.has_v2:
    comp = {arm: {"v1_fc": run.v2_summary[arm]["v1_fully_correct"], "v2_fc": run.v2_summary[arm]["v2_all_required_facts_matched"],
                  "v1_cov": run.v2_summary[arm]["v1_answer_keyword_coverage"], "v2_cov": run.v2_summary[arm]["v2_answer_fact_coverage"],
                  "v1_cit": run.v2_summary[arm]["v1_answers_with_citation"], "v2_cit": run.v2_summary[arm]["v2_answers_with_citation"]}
            for arm in run.v2_summary}
    df, miss = long_df(comp, {"v1_fc": "All facts matched - original v1", "v2_fc": "All required facts matched - revised v2",
                              "v1_cov": "Answer fact coverage - original v1", "v2_cov": "Answer fact coverage - revised v2",
                              "v1_cit": "Answers with a parsed citation - original v1",
                              "v2_cit": "Answers with a parsed citation - revised v2"})
    chart_block("Original vs revised (0-1, lexical)", df, miss, "Score (0-1)", ".3f", domain_max=1.15)
    st.dataframe(pd.DataFrame({ARMS[a]["label"]: {
        "Questions whose correctness changed (v1 -> v2)": ", ".join(x["changed_vs_v1"]) or "none",
        "Citation ID validity (v2) [IDs exist - not factual support]": fmt(x["v2_citation_id_validity"], "pct"),
        "Cited-chunk fact support (v2) [lexical]": fmt(x["v2_cited_chunk_fact_support"], "pct"),
        "False abstentions (v2)": str(x["v2_false_abstentions"]),
        "Automated triage: none / retrieval / generation": " / ".join(str(x["failure_types"][k]) for k in ("none", "retrieval", "generation")),
    } for a, x in run.v2_summary.items()}), use_container_width=True)
    if any(x["v2_cited_chunk_fact_support"] is None for x in run.v2_summary.values()):
        st.caption("Cited-chunk fact support (v2) is N/A for this run: it stored only 160-character previews, not full "
                   "chunk text. Runs made after this change store full text and will report it.")
    with st.expander("Scoring revisions (required facts) and rationale"):
        for q, rv in revisions.get("required_keywords", {}).items():
            st.markdown(f"- **{q}** required: {', '.join(f'`{k}`' for k in rv['required'])} - {rv['rationale']}")
else:
    st.info("Revised (v2) scores not computed for this run (N/A).")

# ------------------------------------------------------------------ failure analysis
st.divider()
st.subheader("Retrieval vs generation failures")
fa = run.failure_analysis
if run.has_v2:
    rows = []
    focus = list(fa.get("questions", {})) or sorted({k[0] for k, v in run.v2.items()
                                                     if v.get("triage", {}).get("failure_type") not in ("none", None)},
                                                    key=lambda x: int(x[1:]))
    for q in focus:
        for arm in ARMS:
            row = run.v2.get((q, arm))
            if not row:
                continue
            rv = fa.get("questions", {}).get(q, {}).get(arm, {})
            t = row.get("triage", {})
            rows.append({"Q": q, "Strategy": ARMS[arm]["label"].split(" (")[0],
                         "Evidence retrieved [token match]": t.get("evidence", "N/A"),
                         "Answer status (v2) [lexical]": t.get("answer", "N/A"),
                         "Automated failure type": t.get("failure_type", "N/A"),
                         "Reviewer: failure type": rv.get("failure", "N/A"),
                         "Reviewer reading (semantic, not verified)": rv.get("semantic_reading", "N/A"),
                         "_note": rv.get("note", "N/A"), "_arm": arm})
    if rows:
        st.caption("Automated columns: lexical triage from stored metrics (retrieval = an expected passage <90% present in "
                   "the top-5; generation = evidence present but answer misses facts or abstains). Reviewer columns: "
                   + (fa.get("reviewer", "N/A") if fa else "no reviewer file for this run (N/A)."))
        fdf = pd.DataFrame(rows)
        st.dataframe(fdf.drop(columns=["_note", "_arm"]), hide_index=True, use_container_width=True,
                     height=36 * (len(fdf) + 1) + 4)
        if fa:
            st.markdown("**Reviewer notes** (semantic reading by the reviewer named above - not verified, not a metric)")
            for q in dict.fromkeys(fdf["Q"]):
                with st.expander(f"{q} - {gt.get(q, {}).get('question', '')}"):
                    for _, rr in fdf[fdf["Q"] == q].iterrows():
                        st.markdown(f"<span style='border-left:6px solid {ARMS[rr['_arm']]['color']};padding-left:6px'>"
                                    f"<b>{ARMS[rr['_arm']]['label']}</b></span> - automated: <code>{rr['Automated failure type']}</code>"
                                    f" · reviewer: <code>{rr['Reviewer: failure type']}</code> · "
                                    f"<i>{rr['Reviewer reading (semantic, not verified)']}</i>", unsafe_allow_html=True)
                        st.caption(rr["_note"])
    else:
        st.caption("No failures to analyze in this run.")
else:
    st.info("Failure triage needs revised (v2) rescoring for this run (N/A).")

# ------------------------------------------------------------------ question detail
st.divider()
q = gt.get(qid, {})
st.subheader(f"{qid} · {q.get('question_type', 'N/A')} · {q.get('difficulty', 'N/A')}")
st.markdown(f"**Question:** {q.get('question', 'N/A')}")
st.markdown(f"**Expected answer:** {q.get('answer', 'N/A')}")
rq = revisions.get("required_keywords", {}).get(qid)
st.caption("Ground-truth facts (v1): " + (", ".join(f"`{k}`" for k in q.get("answer_keywords", [])) or "none - unanswerable")
           + (f" · Revised required facts (v2): {', '.join(f'`{k}`' for k in rq['required'])} - {rq['rationale']}" if rq else "")
           + " · Expected sources: " + (", ".join(f"{s['document']} p.{s['page']}" for s in q.get("sources", [])) or "none"))

recs = {r["arm"]: r for r in run.records if r["id"] == qid}
for col, (arm, meta) in zip(st.columns(len(ARMS)), ARMS.items()):
    with col:
        st.markdown(f"<h4 style='border-left:6px solid {meta['color']};padding-left:8px'>{meta['label']}</h4>",
                    unsafe_allow_html=True)
        r = recs.get(arm)
        if r is None:
            st.info("No record for this arm in this run.")
            continue
        v2r = (run.v2.get((qid, arm)) or {}).get("v2") or {}
        st.caption(f"Knowledge Base `{r['knowledge_base_id']}` · status `{r['status']}` · stop `{fmt(r['stop_reason'])}`"
                   + (" · LEGACY record" if r["schema"] == "legacy" else ""))
        if r["status"] == "error":
            st.error(f"Error recorded (no answer generated): {r['error']}")
        st.markdown("**Generated answer**")
        answer_md = "\n".join(f"> {line}" for line in r["answer"].splitlines()) if r.get("answer") else None
        st.markdown(answer_md or "> N/A (retrieval-only or no answer)")   # quote every line of multi-paragraph answers
        cited_v2 = v2r.get("cited_ids")
        st.caption(f"Cited sources - original v1 parser: {', '.join(f'S{n}' for n in r['cited_sources']) or 'none'}"
                   f" · revised v2 parser: {', '.join(f'S{n}' for n in cited_v2) if cited_v2 is not None else 'N/A'}"
                   + (f" · extra citation text (not verified): {'; '.join(v2r['extra_citation_text'])}"
                      if v2r.get("extra_citation_text") else ""))
        rows = [
            ("Answer: all facts matched [string]", fmt(r["fully_correct"]), fmt(v2r.get("all_required_facts_matched"))),
            ("Answer: fact coverage [string]", fmt(r["answer_keyword_coverage"], "pct"), fmt(v2r.get("answer_fact_coverage"), "pct")),
            ("Missing facts", "-", ", ".join(v2r["missing_facts"]) if v2r.get("missing_facts") else ("none" if v2r else "N/A")),
            ("Retrieval: fact recall@k [string]", fmt(r["keyword_recall"], "pct"), fmt(v2r.get("retrieved_fact_recall"), "pct")),
            ("Retrieval: passage evidence [token]", fmt(r["passage_evidence_coverage"], "pct"), "same as v1"),
            ("Retrieval: all passages present [>=90%]", fmt(r["all_passages_present"]), "same as v1"),
            ("Retrieval: page-label hit [informational]", fmt(r["page_label_hit"], "pct"), "same as v1"),
            ("Citation ID validity [not factual support]", fmt(r["citation_id_validity"]), fmt(v2r.get("citation_id_validity"))),
            ("Cited-chunk support [lexical]", fmt(r["cited_chunk_keyword_support"], "pct"), fmt(v2r.get("cited_chunk_fact_support"), "pct")),
            ("Unanswerable handled correctly", fmt(r["abstention_correct"]), fmt(v2r.get("abstention_correct"))),
            ("Truncated", fmt(r["truncated"]), fmt(v2r.get("truncated"))),
            ("Retrieve / generate latency", f"{fmt(r['retrieve_ms'], 'ms')} / {fmt(r['generate_ms'], 'ms')}", "-"),
            ("Tokens in / out", f"{fmt(r['input_tokens'], 'int')} / {fmt(r['output_tokens'], 'int')}", "-"),
            ("Estimated cost", fmt(r["cost_usd"], "usd"), "-"),
        ]
        mdf = pd.DataFrame(rows, columns=["Metric", "Original (v1)", "Revised (v2)"])
        st.dataframe(mdf, hide_index=True, use_container_width=True, height=36 * (len(mdf) + 1) + 4)

        st.markdown("**Retrieved sources** (preview: first 160 characters)")
        src = pd.DataFrame([{"#": f"S{i}", "Document": s.get("document"), "Page label": fmt(s.get("page")),
                             "Score": round(s["score"], 3) if s.get("score") is not None else "N/A",
                             "Cited (v2)": "yes" if cited_v2 and i in cited_v2 else "",
                             "Preview": s.get("preview", "N/A")} for i, s in enumerate(r["sources"], 1)])
        if src.empty:
            st.caption("No sources retrieved.")
        else:
            st.dataframe(src, hide_index=True, use_container_width=True)
        if r["passages"]:
            st.markdown("**Passage evidence per expected source** [token match]")
            st.dataframe(pd.DataFrame([{"Document": p["document"], "Expected page": p["page"], "Coverage": fmt(p["coverage"], "pct"),
                                        "Present (>=90%)": fmt(p["present"])} for p in r["passages"]]),
                         hide_index=True, use_container_width=True)
