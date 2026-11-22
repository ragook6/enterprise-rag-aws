"""
Read-only data layer for the RAG experiment dashboard.

- Discovers evaluation runs under results/<run-id>/ automatically.
- Normalizes two record schemas:
    * "current": metric-fix schema (passage_evidence_coverage, source_page_label_hit,
                 citation_id_validity, cited_chunk_keyword_support)
    * "legacy" : pre-fix schema (source_page_hit, citation_validity; no passage evidence)
- Metrics that a record does not contain are returned as None (rendered "N/A"),
  never estimated or back-filled.
No AWS SDKs are imported here; everything comes from local files.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
import os  # noqa: E402

# Results location: $RAG_RESULTS_DIR, else private results/ (local only), else the sanitized results-public/.
RESULTS_DIR = Path(os.environ["RAG_RESULTS_DIR"]) if os.environ.get("RAG_RESULTS_DIR") else (
    ROOT / "results" if (ROOT / "results").is_dir() else ROOT / "results-public")
GROUND_TRUTH = ROOT / "data" / "evaluation" / "ground_truth.json"

# Fixed identity per arm (never re-assigned by rank or filter). Colors: reference categorical slots 1 and 2.
ARMS = {
    "baseline-fixed100": {"label": "Fixed-size (100 tokens)", "color": "#2a78d6"},
    "improved-hierarchical": {"label": "Hierarchical (1500/300 tokens)", "color": "#eb6834"},
}

METRIC_LABELS = {
    "answer_keyword_coverage": "Answer: expected-fact coverage [string match]",
    "fully_correct": "Answer: all expected facts matched [string match]",
    "keyword_recall": "Retrieval: expected-fact recall@k [string match]",
    "passage_evidence_coverage": "Retrieval: passage-evidence coverage@k [token match]",
    "all_passages_present": "Retrieval: all expected passages present [>=90% tokens]",
    "source_doc_hit": "Retrieval: expected documents retrieved",
    "page_label_hit": "Retrieval: page-label hit [informational]",
    "citation_id_validity": "Citation ID validity [IDs exist - not factual support]",
    "cited_chunk_keyword_support": "Cited-chunk keyword support [lexical - not semantic]",
    "abstention_correct": "Unanswerable handled correctly",
    "false_abstention": "False abstention",
    "truncated": "Truncated (max_tokens)",
}


@dataclass
class Run:
    run_id: str
    path: Path
    meta: dict
    records: list[dict] = field(default_factory=list)
    v2: dict = field(default_factory=dict)            # (id, arm) -> rescored_v2 row; empty if not rescored
    v2_summary: dict = field(default_factory=dict)
    v2_meta: dict = field(default_factory=dict)
    failure_analysis: dict = field(default_factory=dict)

    @property
    def has_v2(self) -> bool:
        return bool(self.v2)

    @property
    def schema(self) -> str:
        kinds = {r["schema"] for r in self.records}
        return "legacy" if kinds == {"legacy"} else ("mixed" if len(kinds) > 1 else "current")

    @property
    def retrieval_only(self) -> bool:
        return bool(self.meta.get("retrieval_only"))

    @property
    def question_ids(self) -> list[str]:
        seen = []
        for r in self.records:
            if r["id"] not in seen:
                seen.append(r["id"])
        return sorted(seen, key=lambda q: int(q[1:]) if q[1:].isdigit() else q)


def _schema_of(rec: dict) -> str:
    ret, sc = rec.get("retrieval", {}), rec.get("scores", {})
    if "source_page_hit" in ret or "citation_validity" in sc or "passage_evidence_coverage" not in ret:
        return "legacy"
    return "current"


def normalize(rec: dict) -> dict:
    """Flatten one results.jsonl record into a fixed set of keys; absent metrics -> None."""
    ret, sc = rec.get("retrieval", {}) or {}, rec.get("scores", {}) or {}
    schema = _schema_of(rec)
    return {
        "schema": schema,
        "id": rec.get("id"), "arm": rec.get("arm"), "knowledge_base_id": rec.get("knowledge_base_id"),
        "question": rec.get("question"), "question_type": rec.get("question_type"),
        "difficulty": rec.get("difficulty"), "expected_answer": rec.get("expected_answer"),
        "status": rec.get("status"), "error": rec.get("error"),
        "answer": rec.get("answer"), "stop_reason": rec.get("stop_reason"),
        "sources": rec.get("sources", []),
        "retrieve_ms": rec.get("retrieve_ms"), "generate_ms": rec.get("generate_ms"),
        "generate_wall_ms": rec.get("generate_wall_ms"),
        "input_tokens": rec.get("input_tokens"), "output_tokens": rec.get("output_tokens"),
        "cost_usd": rec.get("cost_usd"), "request_id": rec.get("request_id"),
        # retrieval metrics
        "keyword_recall": ret.get("keyword_recall"),
        "source_doc_hit": ret.get("source_doc_hit"),
        "page_label_hit": ret.get("source_page_label_hit", ret.get("source_page_hit")),
        "passage_evidence_coverage": ret.get("passage_evidence_coverage"),   # None for legacy
        "all_passages_present": ret.get("all_passages_present"),             # None for legacy
        "passages": ret.get("passages", []),
        "num_chunks": ret.get("num_chunks"), "context_chars": ret.get("context_chars"),
        # answer metrics
        "answer_keyword_coverage": sc.get("answer_keyword_coverage"),
        "fully_correct": sc.get("fully_correct"),
        "abstained": sc.get("abstained"),
        "abstention_correct": sc.get("abstention_correct"),
        "false_abstention": sc.get("false_abstention"),
        "partial_answer_flagged": sc.get("partial_answer_flagged"),
        "cited_sources": sc.get("cited_sources", []),
        "citation_id_validity": sc.get("citation_id_validity", sc.get("citation_validity")),
        "cited_chunk_keyword_support": sc.get("cited_chunk_keyword_support"),  # None for legacy
        "truncated": sc.get("truncated"),
    }


def discover_runs(results_dir: Path = RESULTS_DIR) -> list[Run]:
    """Every results/<run-id>/ with run_metadata.json + results.jsonl, newest first."""
    runs = []
    if not results_dir.is_dir():
        return runs
    for d in results_dir.iterdir():
        meta_f, res_f = d / "run_metadata.json", d / "results.jsonl"
        if not (d.is_dir() and meta_f.is_file() and res_f.is_file()):
            continue
        try:
            meta = json.loads(meta_f.read_text())
            records = [normalize(json.loads(line)) for line in res_f.read_text().splitlines() if line.strip()]
        except (json.JSONDecodeError, OSError):
            continue  # unreadable/partial run: skip rather than guess
        run = Run(run_id=meta.get("run_id", d.name), path=d, meta=meta, records=records)
        _attach_v2(run)
        runs.append(run)
    return sorted(runs, key=lambda r: r.run_id, reverse=True)


def _attach_v2(run: Run, analysis_dir: Path | None = None) -> None:
    """Attach optional rescored_v2.* files and a reviewer failure-analysis file; absent -> left empty."""
    d = run.path
    try:
        if (d / "rescored_v2.jsonl").is_file():
            for line in (d / "rescored_v2.jsonl").read_text().splitlines():
                if line.strip():
                    row = json.loads(line)
                    run.v2[(row["id"], row["arm"])] = row
            run.v2_summary = json.loads((d / "rescored_v2_summary.json").read_text())
            run.v2_meta = json.loads((d / "rescored_v2_metadata.json").read_text())
        fa = (analysis_dir or GROUND_TRUTH.parent) / f"failure_analysis_{run.run_id}.json"
        if fa.is_file():
            run.failure_analysis = json.loads(fa.read_text())
    except (json.JSONDecodeError, OSError, KeyError):
        run.v2, run.v2_summary, run.v2_meta = {}, {}, {}   # unreadable rescoring -> treated as not available


def load_ground_truth(path: Path = GROUND_TRUTH) -> dict:
    return {q["id"]: q for q in json.loads(path.read_text())["questions"]}


def _mean(values) -> float | None:
    vals = [float(v) for v in values if v is not None]
    return round(sum(vals) / len(vals), 4) if vals else None


def summarize_run(run: Run) -> dict[str, dict]:
    """Per-arm aggregates computed from records (not from summary.json), None when unavailable."""
    out = {}
    for arm in [a for a in ARMS if any(r["arm"] == a for r in run.records)]:
        rs = [r for r in run.records if r["arm"] == arm and r["status"] in ("ok", "retrieval_only")]
        out[arm] = {
            "questions": len([r for r in run.records if r["arm"] == arm]),
            "ok": len(rs),
            "errors": len([r for r in run.records if r["arm"] == arm and r["status"] == "error"]),
            **{m: _mean(r[m] for r in rs) for m in (
                "answer_keyword_coverage", "fully_correct", "keyword_recall", "passage_evidence_coverage",
                "all_passages_present", "source_doc_hit", "page_label_hit", "citation_id_validity",
                "cited_chunk_keyword_support", "retrieve_ms", "generate_ms")},
            "input_tokens": sum(r["input_tokens"] or 0 for r in rs) if any(r["input_tokens"] is not None for r in rs) else None,
            "output_tokens": sum(r["output_tokens"] or 0 for r in rs) if any(r["output_tokens"] is not None for r in rs) else None,
            "cost_usd": round(sum(r["cost_usd"] or 0 for r in rs), 8) if any(r["cost_usd"] is not None for r in rs) else None,
        }
    return out


def fmt(value, kind: str = "num") -> str:
    """Display helper: None -> 'N/A'; never invents a value."""
    if value is None:
        return "N/A"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if kind == "pct":
        return f"{float(value) * 100:.0f}%"
    if kind == "usd":
        return f"${float(value):.6f}"
    if kind == "ms":
        return f"{float(value):.0f} ms"
    if kind == "int":
        return f"{int(value):,}"
    return f"{value}"
