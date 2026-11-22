#!/usr/bin/env python3
"""
Offline re-scoring of saved evaluation runs with the v2 lexical scoring (scripts/scoring_v2.py).

    .venv/bin/python scripts/rescore_results.py                 # every run under results/
    .venv/bin/python scripts/rescore_results.py --run 20261121T231031Z

Reads results/<run>/results.jsonl and writes NEW files next to it:
    rescored_v2.jsonl          per record: original (v1) scores, revised (v2) scores, failure triage
    rescored_v2_summary.json   per arm: v1 vs v2 aggregates
    rescored_v2_metadata.json  scoring version, revisions hash, hashes of the untouched originals
Original files (results.jsonl, summary.json, summary.md, run_metadata.json) are never modified; their SHA-256
is checked before and after. No AWS calls.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scoring_v2 as v2  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ORIGINALS = ("results.jsonl", "summary.json", "summary.md", "run_metadata.json")
ABSTAIN_FALLBACK = "The provided documents do not contain this information."


def sha(p: Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def _mean(vals):
    vals = [float(v) for v in vals if v is not None]
    return round(sum(vals) / len(vals), 4) if vals else None


def rescore_run(run_dir: Path, gt: dict, revisions: dict, abstain_text: str) -> dict:
    before = {f: sha(run_dir / f) for f in ORIGINALS}
    recs = [json.loads(l) for l in (run_dir / "results.jsonl").read_text().splitlines() if l.strip()]
    out = []
    for r in recs:
        q = gt.get(r.get("id"))
        row = {"id": r.get("id"), "arm": r.get("arm"), "status": r.get("status"),
               "question_type": r.get("question_type")}
        sc, ret = r.get("scores", {}) or {}, r.get("retrieval", {}) or {}
        row["v1"] = {"answer_keyword_coverage": sc.get("answer_keyword_coverage"),
                     "fully_correct": sc.get("fully_correct"),
                     "citation_id_validity": sc.get("citation_id_validity", sc.get("citation_validity")),
                     "cited_sources": sc.get("cited_sources", []),
                     "abstained": sc.get("abstained"),
                     "passage_evidence_coverage": ret.get("passage_evidence_coverage"),
                     "all_passages_present": ret.get("all_passages_present")}
        if r.get("status") != "ok" or q is None or r.get("answer") is None:
            row["v2"], row["triage"] = None, {"failure_type": "not scored", "reason": r.get("error") or r.get("status")}
        else:
            sources = r.get("sources", [])
            texts = [s["text"] for s in sources] if sources and all("text" in s for s in sources) else None
            row["v2"] = v2.score_answer_v2(q, r["answer"], abstain_text, r.get("stop_reason"), revisions,
                                           texts, len(sources))
            row["v2"]["chunk_text_available"] = texts is not None
            row["triage"] = v2.classify_failure(r, row["v2"])
        out.append(row)

    summary = {}
    for arm in sorted({o["arm"] for o in out}):
        rows = [o for o in out if o["arm"] == arm and o["v2"] is not None]
        summary[arm] = {
            "n_scored": len(rows),
            "v1_fully_correct": _mean(o["v1"]["fully_correct"] for o in rows),
            "v2_all_required_facts_matched": _mean(o["v2"]["all_required_facts_matched"] for o in rows),
            "v1_answer_keyword_coverage": _mean(o["v1"]["answer_keyword_coverage"] for o in rows),
            "v2_answer_fact_coverage": _mean(o["v2"]["answer_fact_coverage"] for o in rows),
            "v1_answers_with_citation": _mean(bool(o["v1"]["cited_sources"]) for o in rows),
            "v2_answers_with_citation": _mean(bool(o["v2"]["cited_ids"]) for o in rows),
            "v2_citation_id_validity": _mean(o["v2"]["citation_id_validity"] for o in rows),
            "v2_cited_chunk_fact_support": _mean(o["v2"]["cited_chunk_fact_support"] for o in rows),
            "v2_false_abstentions": sum(bool(o["v2"]["false_abstention"]) for o in rows),
            "changed_vs_v1": [o["id"] for o in rows
                              if o["v1"]["fully_correct"] is not None
                              and o["v1"]["fully_correct"] != o["v2"]["all_required_facts_matched"]],
            "failure_types": {t: sum(o["triage"]["failure_type"] == t for o in rows)
                              for t in ("none", "retrieval", "generation", "unknown")},
        }

    with open(run_dir / "rescored_v2.jsonl", "w") as fh:
        for o in out:
            fh.write(json.dumps(o) + "\n")
    (run_dir / "rescored_v2_summary.json").write_text(json.dumps(summary, indent=2))
    after = {f: sha(run_dir / f) for f in ORIGINALS}
    if before != after:
        raise RuntimeError(f"original files changed during rescoring in {run_dir}")
    meta = {"scoring_version": v2.SCORING_VERSION, "rescored_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "revisions_sha256": revisions["_sha256"], "original_file_sha256": before,
            "records": len(out), "note": "Lexical scoring only; semantic support is not verified."}
    (run_dir / "rescored_v2_metadata.json").write_text(json.dumps(meta, indent=2))
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", nargs="*", help="run IDs (default: all)")
    ap.add_argument("--results-dir", default=str(ROOT / "results"))
    args = ap.parse_args(argv)
    gt = {q["id"]: q for q in json.loads((ROOT / "data/evaluation/ground_truth.json").read_text())["questions"]}
    cfg = json.loads((ROOT / "experiments/experiment_config.json").read_text())
    abstain = cfg["controlled_variables"]["generation"].get("abstain_text", ABSTAIN_FALLBACK)
    revisions = v2.load_revisions()
    runs = [d for d in sorted(Path(args.results_dir).iterdir())
            if (d / "results.jsonl").exists() and (not args.run or d.name in args.run)]
    for d in runs:
        s = rescore_run(d, gt, revisions, abstain)
        print(f"{d.name}: " + "; ".join(f"{a}: v1 {x['v1_fully_correct']} -> v2 {x['v2_all_required_facts_matched']}"
                                        f" (changed {x['changed_vs_v1']})" for a, x in s.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
