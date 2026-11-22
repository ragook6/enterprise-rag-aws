#!/usr/bin/env python3
"""
RAG chunking experiment runner: Bedrock Knowledge Bases (Retrieve) + Amazon Nova Micro (Converse).

For every question x arm (Knowledge Base):
  1. Retrieve top-K chunks              (bedrock-agent-runtime Retrieve, semantic search)
  2. Build ONE prompt from those chunks (same system prompt + format for both arms)
  3. Generate the answer                (bedrock-runtime Converse, temperature 0, maxTokens 512)
  4. Score retrieval + answer           (deterministic keyword / source / abstention checks)
and write results/<run-id>/{results.jsonl, summary.json, summary.md, run_metadata.json}.

Usage (all calls run as the MFA-gated runner role, assumed from the hrl-mfa session):
  AWS_PROFILE=hrl-mfa .venv/bin/python scripts/run_evaluation.py --questions Q18      # one question
  AWS_PROFILE=hrl-mfa .venv/bin/python scripts/run_evaluation.py --retrieval-only     # no model calls
  AWS_PROFILE=hrl-mfa .venv/bin/python scripts/run_evaluation.py                      # all 35 x 2 arms
Safety: refuses to run with Bedrock/Anthropic API-key env vars set, requires a valid MFA session,
estimates cost up front and aborts above --max-cost-usd.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "experiments" / "experiment_config.json"
GROUND_TRUTH_PATH = ROOT / "data" / "evaluation" / "ground_truth.json"
CITATION_RE = re.compile(r"\[S(\d+)\]")


# --------------------------------------------------------------------------- config
def load_config(path: Path = CONFIG_PATH) -> dict:
    cfg = json.loads(path.read_text())
    gen = cfg["controlled_variables"]["generation"]
    ret = cfg["controlled_variables"]["retrieval"]
    required = {"inference_profile_id": str, "system_prompt": str, "abstain_text": str,
                "inference_config": dict, "pricing_usd_per_1m_tokens": dict}
    for key, typ in required.items():
        if not isinstance(gen.get(key), typ):
            raise ValueError(f"experiment_config: generation.{key} missing or not {typ.__name__}")
    if gen["abstain_text"] not in gen["system_prompt"]:
        raise ValueError("abstain_text must appear verbatim in system_prompt")
    if not isinstance(ret.get("numberOfResults"), int) or ret["numberOfResults"] < 1:
        raise ValueError("retrieval.numberOfResults must be a positive integer")
    return cfg


def config_fingerprint(cfg: dict) -> str:
    """Hash of everything that must be identical across arms (retrieval + generation)."""
    cv = cfg["controlled_variables"]
    blob = json.dumps({"retrieval": cv["retrieval"], "generation": cv["generation"]}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


# --------------------------------------------------------------------------- retrieval
def retrieve(agent_rt, kb_id: str, question: str, top_k: int) -> tuple[list[dict], int]:
    t0 = time.perf_counter()
    resp = agent_rt.retrieve(
        knowledgeBaseId=kb_id,
        retrievalQuery={"text": question},
        retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": top_k,
                                                              "overrideSearchType": "SEMANTIC"}},
    )
    ms = int((time.perf_counter() - t0) * 1000)
    chunks = []
    for r in resp.get("retrievalResults", []):
        uri = r.get("location", {}).get("s3Location", {}).get("uri", "")
        page = r.get("metadata", {}).get("x-amz-bedrock-kb-document-page-number")
        chunks.append({
            "text": r.get("content", {}).get("text", ""),
            "document": uri.rsplit("/", 1)[-1] if uri else "unknown",
            "page": int(float(page)) if page is not None else None,
            "score": r.get("score"),
        })
    return chunks, ms


def build_user_message(question: str, chunks: list[dict]) -> str:
    blocks = []
    for i, c in enumerate(chunks, 1):
        page = c["page"] if c["page"] is not None else "n/a"
        blocks.append(f"[S{i}] (document: {c['document']}, page: {page})\n{' '.join(c['text'].split())}")
    return "Sources:\n\n" + "\n\n".join(blocks) + f"\n\nQuestion: {question}\nAnswer:"


# --------------------------------------------------------------------------- generation
def generate(bedrock_rt, gen_cfg: dict, user_message: str) -> dict:
    t0 = time.perf_counter()
    resp = bedrock_rt.converse(
        modelId=gen_cfg["inference_profile_id"],
        system=[{"text": gen_cfg["system_prompt"]}],
        messages=[{"role": "user", "content": [{"text": user_message}]}],
        inferenceConfig=dict(gen_cfg["inference_config"]),
    )
    wall_ms = int((time.perf_counter() - t0) * 1000)
    text = "".join(b.get("text", "") for b in resp["output"]["message"]["content"]).strip()
    usage = resp.get("usage", {})
    price = gen_cfg["pricing_usd_per_1m_tokens"]
    cost = usage.get("inputTokens", 0) * price["input"] / 1e6 + usage.get("outputTokens", 0) * price["output"] / 1e6
    return {
        "answer": text,
        "stop_reason": resp.get("stopReason"),
        "input_tokens": usage.get("inputTokens", 0),
        "output_tokens": usage.get("outputTokens", 0),
        "generate_ms": resp.get("metrics", {}).get("latencyMs", wall_ms),
        "generate_wall_ms": wall_ms,
        "cost_usd": round(cost, 8),
        "request_id": resp.get("ResponseMetadata", {}).get("RequestId"),
    }


# --------------------------------------------------------------------------- scoring
def is_abstention(answer: str, abstain_text: str) -> bool:
    return norm(abstain_text).rstrip(".") in norm(answer)


TOKEN_RE = re.compile(r"[a-z0-9]+(?:[./:_-][a-z0-9]+)*")
STOPWORDS = frozenset(
    "a an and are as at be by for from has have in into is it its of on or that the their this to was were "
    "which with within".split())
PASSAGE_PRESENT_THRESHOLD = 0.9


def content_tokens(text: str) -> list[str]:
    """Lower-cased word/identifier tokens (keeps IDs like 10.66.0.0/20, hrl-prod-order-ingest) minus stopwords."""
    return [t for t in TOKEN_RE.findall((text or "").lower()) if t not in STOPWORDS]


def passage_evidence(q: dict, chunks: list[dict]) -> dict:
    """
    LEXICAL evidence check, independent of page labels: for each expected source passage, the share of its
    content tokens that occur in retrieved chunks FROM THE SAME DOCUMENT (pooled, so a passage split across
    two small chunks still counts). Hierarchical parent chunks are labeled with the page where the parent
    starts, so a page-2 passage inside a parent starting on page 1 is credited here but not by the page label.
    """
    per_source = []
    for s in q["sources"]:
        want = content_tokens(s["passage"])
        pool = set(content_tokens(" ".join(c["text"] for c in chunks if c["document"] == s["document"])))
        cov = sum(t in pool for t in want) / len(want) if want else 0.0
        per_source.append({"document": s["document"], "page": s["page"], "coverage": round(cov, 3),
                           "present": cov >= PASSAGE_PRESENT_THRESHOLD})
    if not per_source:
        return {"passage_evidence_coverage": None, "all_passages_present": None, "passages": []}
    return {"passage_evidence_coverage": round(sum(p["coverage"] for p in per_source) / len(per_source), 3),
            "all_passages_present": all(p["present"] for p in per_source),
            "passages": per_source}


def score_retrieval(q: dict, chunks: list[dict]) -> dict:
    ctx = norm(" ".join(c["text"] for c in chunks))
    kws = q["answer_keywords"]
    expected_docs = {s["document"] for s in q["sources"]}
    expected_pages = {(s["document"], s["page"]) for s in q["sources"]}
    got_docs = {c["document"] for c in chunks}
    got_pages = {(c["document"], c["page"]) for c in chunks if c["page"] is not None}
    return {
        # string match of the expected answer facts anywhere in the retrieved text
        "keyword_recall": round(sum(norm(k) in ctx for k in kws) / len(kws), 3) if kws else None,
        "source_doc_hit": expected_docs <= got_docs if expected_docs else None,
        # INFORMATIONAL: Bedrock page label; hierarchical parents carry their starting page only
        "source_page_label_hit": (round(len(expected_pages & got_pages) / len(expected_pages), 3)
                                  if expected_pages and got_pages else None),
        **passage_evidence(q, chunks),
        "retrieved_docs": sorted(got_docs),
        "num_chunks": len(chunks),
        "context_chars": sum(len(c["text"]) for c in chunks),
    }


def score_answer(q: dict, answer: str, abstain_text: str, chunks: list[dict], stop_reason: str | None) -> dict:
    """
    All checks are LEXICAL (string/token matching). None verifies semantic support - that would need a human
    or an LLM judge, which this experiment deliberately does not use.
    """
    abstained = is_abstention(answer, abstain_text)
    kws = q["answer_keywords"]
    ans = norm(answer)
    coverage = round(sum(norm(k) in ans for k in kws) / len(kws), 3) if kws else None
    cited = sorted({int(n) for n in CITATION_RE.findall(answer)})
    ids_valid = all(1 <= n <= len(chunks) for n in cited) if cited else None
    # Lexical support: of the expected facts that the answer states, how many also appear in the chunks it cites?
    stated = [k for k in kws if norm(k) in ans]
    cited_text = norm(" ".join(chunks[n - 1]["text"] for n in cited if 1 <= n <= len(chunks)))
    cited_support = (round(sum(norm(k) in cited_text for k in stated) / len(stated), 3)
                     if stated and cited else None)
    unanswerable = q["question_type"] == "unanswerable"
    return {
        "abstained": abstained,
        "answer_keyword_coverage": None if unanswerable else coverage,
        "fully_correct": None if unanswerable else (coverage == 1.0),   # = all expected facts string-matched
        "abstention_correct": abstained if unanswerable else None,
        "false_abstention": None if unanswerable else abstained,
        "partial_answer_flagged": "not covered:" in ans,
        "cited_sources": cited,
        "citation_id_validity": ids_valid,              # IDs exist in the context; NOT factual support
        "cited_chunk_keyword_support": cited_support,   # lexical only; NOT verified semantic support
        "has_citation": bool(cited),
        "truncated": stop_reason == "max_tokens",
    }


# --------------------------------------------------------------------------- one item
def evaluate_one(q: dict, arm: str, kb_id: str, cfg: dict, agent_rt, bedrock_rt, retrieval_only: bool) -> dict:
    gen_cfg = cfg["controlled_variables"]["generation"]
    top_k = cfg["controlled_variables"]["retrieval"]["numberOfResults"]
    rec = {"id": q["id"], "arm": arm, "knowledge_base_id": kb_id, "question_type": q["question_type"],
           "difficulty": q["difficulty"], "question": q["question"], "expected_answer": q["answer"]}
    try:
        chunks, rms = retrieve(agent_rt, kb_id, q["question"], top_k)
        rec.update({"retrieve_ms": rms, "sources": [{k: c[k] for k in ("document", "page", "score")}
                                                     | {"preview": " ".join(c["text"].split())[:160],
                                                        "text": c["text"]}   # full text enables v2 rescoring
                                                     for c in chunks]})
        rec["retrieval"] = score_retrieval(q, chunks)
        if retrieval_only:
            return rec | {"status": "retrieval_only"}
        if not chunks:  # nothing to ground on -> abstain without calling the model
            gen = {"answer": gen_cfg["abstain_text"], "stop_reason": "no_context", "input_tokens": 0,
                   "output_tokens": 0, "generate_ms": 0, "generate_wall_ms": 0, "cost_usd": 0.0, "request_id": None}
        else:
            gen = generate(bedrock_rt, gen_cfg, build_user_message(q["question"], chunks))
        rec.update(gen)
        rec["scores"] = score_answer(q, gen["answer"], gen_cfg["abstain_text"], chunks, gen["stop_reason"])
        rec["status"] = "ok"
    except Exception as e:  # record and continue; never fabricate an answer
        rec.update({"status": "error", "error": f"{type(e).__name__}: {str(e)[:300]}"})
    return rec


# --------------------------------------------------------------------------- summary
def summarize(records: list[dict]) -> dict:
    def mean(vals):
        vals = [v for v in vals if v is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    out = {}
    for arm in sorted({r["arm"] for r in records}):
        rs = [r for r in records if r["arm"] == arm]
        ok = [r for r in rs if r.get("status") in ("ok", "retrieval_only")]
        by_type = {}
        for t in sorted({r["question_type"] for r in rs}):
            tr = [r for r in ok if r["question_type"] == t]
            by_type[t] = {
                "n": len(tr),
                "keyword_recall@k": mean([r["retrieval"]["keyword_recall"] for r in tr]),
                "passage_evidence_coverage@k": mean([r["retrieval"]["passage_evidence_coverage"] for r in tr]),
                "source_doc_hit@k": mean([float(r["retrieval"]["source_doc_hit"]) for r in tr
                                          if r["retrieval"]["source_doc_hit"] is not None]),
                "answer_keyword_coverage": mean([r.get("scores", {}).get("answer_keyword_coverage") for r in tr]),
                "fully_correct": mean([float(r["scores"]["fully_correct"]) for r in tr
                                       if r.get("scores", {}).get("fully_correct") is not None]),
            }
        scores = [r["scores"] for r in ok if "scores" in r]
        out[arm] = {
            "questions": len(rs), "ok": len(ok), "errors": sum(r.get("status") == "error" for r in rs),
            "keyword_recall@k": mean([r["retrieval"]["keyword_recall"] for r in ok]),
            "passage_evidence_coverage@k": mean([r["retrieval"]["passage_evidence_coverage"] for r in ok]),
            "all_passages_present@k": mean([float(r["retrieval"]["all_passages_present"]) for r in ok
                                            if r["retrieval"]["all_passages_present"] is not None]),
            "source_doc_hit@k": mean([float(r["retrieval"]["source_doc_hit"]) for r in ok
                                      if r["retrieval"]["source_doc_hit"] is not None]),
            "source_page_label_hit@k (informational)": mean([r["retrieval"]["source_page_label_hit"] for r in ok]),
            "answer_keyword_coverage": mean([s["answer_keyword_coverage"] for s in scores]),
            "fully_correct_rate": mean([float(s["fully_correct"]) for s in scores if s["fully_correct"] is not None]),
            "abstention_correct": [s["abstention_correct"] for s in scores if s["abstention_correct"] is not None],
            "false_abstentions": sum(bool(s["false_abstention"]) for s in scores),
            "answers_with_citations": mean([float(s["has_citation"]) for s in scores]),
            "invalid_citation_ids": sum(s["citation_id_validity"] is False for s in scores),
            "cited_chunk_keyword_support": mean([s["cited_chunk_keyword_support"] for s in scores]),
            "truncated": sum(bool(s["truncated"]) for s in scores),
            "input_tokens": sum(r.get("input_tokens", 0) for r in ok),
            "output_tokens": sum(r.get("output_tokens", 0) for r in ok),
            "avg_context_chars": mean([r["retrieval"]["context_chars"] for r in ok]),
            "avg_retrieve_ms": mean([r.get("retrieve_ms") for r in ok]),
            "avg_generate_ms": mean([r.get("generate_ms") for r in ok if "generate_ms" in r]),
            "cost_usd": round(sum(r.get("cost_usd", 0) for r in ok), 6),
            "by_question_type": by_type,
        }
    return out


def summary_markdown(summary: dict, meta: dict) -> str:
    arms = list(summary)
    rows = [("Questions OK / errors", lambda s: f"{s['ok']} / {s['errors']}"),
            ("Retrieval: expected-fact keyword recall@k [string match]", lambda s: s["keyword_recall@k"]),
            ("Retrieval: passage-evidence coverage@k [token match, same doc]", lambda s: s["passage_evidence_coverage@k"]),
            ("Retrieval: all expected passages present@k [>=90% tokens]", lambda s: s["all_passages_present@k"]),
            ("Retrieval: expected documents retrieved@k", lambda s: s["source_doc_hit@k"]),
            ("Retrieval: page-label hit@k [informational only]", lambda s: s["source_page_label_hit@k (informational)"]),
            ("Answer: expected-fact keyword coverage [string match]", lambda s: s["answer_keyword_coverage"]),
            ("Answer: all expected facts matched [string match]", lambda s: s["fully_correct_rate"]),
            ("Unanswerable handled correctly (exact abstain sentence)", lambda s: s["abstention_correct"]),
            ("False abstentions", lambda s: s["false_abstentions"]),
            ("Answers with citations", lambda s: s["answers_with_citations"]),
            ("Invalid citation IDs [ID validity, not factual support]", lambda s: s["invalid_citation_ids"]),
            ("Cited-chunk keyword support [lexical, not semantic]", lambda s: s["cited_chunk_keyword_support"]),
            ("Truncated answers", lambda s: s["truncated"]),
            ("Avg context chars", lambda s: s["avg_context_chars"]),
            ("Input / output tokens", lambda s: f"{s['input_tokens']} / {s['output_tokens']}"),
            ("Avg retrieve / generate ms", lambda s: f"{s['avg_retrieve_ms']} / {s['avg_generate_ms']}"),
            ("Estimated cost USD", lambda s: s["cost_usd"])]
    md = [f"# RAG evaluation {meta['run_id']}", "",
          f"Model `{meta['model']}` | top-k {meta['top_k']} | config fingerprint `{meta['config_fingerprint']}`", "",
          "| Metric | " + " | ".join(arms) + " |", "|---|" + "---|" * len(arms)]
    md += [f"| {name} | " + " | ".join(str(f(summary[a])) for a in arms) + " |" for name, f in rows]
    md += ["", "## Metric notes", METRIC_NOTES]
    return "\n".join(md) + "\n"


METRIC_NOTES = """- **All scores are lexical (string/token matching). Semantic support is NOT verified** - no human review
  and no LLM judge. A matched keyword can appear in a wrong statement, and a correct paraphrase can score low.
- **Expected-fact keyword recall / coverage**: share of `answer_keywords` found verbatim (case/whitespace-
  insensitive) in the retrieved text / the answer. "All expected facts matched" means every keyword matched.
- **Passage-evidence coverage**: share of each expected source passage's content tokens (stopwords removed)
  present in retrieved chunks *from the same document*, pooled across chunks; "present" = at least 90%.
  Independent of page labels and of chunk boundaries.
- **Page-label hit (informational)**: compares Bedrock's page label with the expected page. Hierarchical parent
  chunks carry only their *starting* page, so this under-counts the hierarchical arm (e.g. Q18).
- **Citation ID validity**: every `[S#]` refers to a provided source. It does **not** check that the source
  supports the claim. **Cited-chunk keyword support** checks lexically whether expected facts stated in the
  answer also appear in the cited chunks - still not semantic verification.
- The same scoring functions are applied to both Knowledge Bases."""


# --------------------------------------------------------------------------- AWS wiring
def runner_clients(profile: str, region: str):
    import boto3
    from botocore.config import Config

    for var in ("AWS_BEARER_TOKEN_BEDROCK", "ANTHROPIC_AWS_API_KEY", "ANTHROPIC_API_KEY"):
        if os.environ.get(var):
            sys.exit(f"Refusing to run: {var} is set (this runner uses SigV4 role credentials only).")
    chk = subprocess.run([sys.executable, str(ROOT / "scripts/check_mfa_session.py"), "--profile", profile,
                          "--min-minutes", "10"], capture_output=True, text=True)
    if chk.returncode != 0:
        sys.exit("STOP: MFA session check failed - run scripts/mfa_session.py\n" + chk.stdout)
    out = json.loads(subprocess.check_output(["terraform", f"-chdir={ROOT / 'infra'}", "output", "-json"]))
    src = boto3.Session(profile_name=profile, region_name=region)
    c = src.client("sts").assume_role(RoleArn=out["runner_role_arn"]["value"],
                                      RoleSessionName="rag-evaluation", DurationSeconds=3600)["Credentials"]
    sess = boto3.Session(aws_access_key_id=c["AccessKeyId"], aws_secret_access_key=c["SecretAccessKey"],
                         aws_session_token=c["SessionToken"], region_name=region)
    ident = sess.client("sts").get_caller_identity()["Arn"]
    if ":assumed-role/hrl-rag-experiment-runner/" not in ident:
        sys.exit(f"STOP: unexpected identity {ident}")
    retry = Config(retries={"total_max_attempts": 3, "mode": "standard"})
    arms = {k: v["knowledge_base_id"] for k, v in out["experiments"]["value"].items()}
    return sess.client("bedrock-agent-runtime", config=retry), sess.client("bedrock-runtime", config=retry), arms, ident


def estimate_cost(questions: list, n_arms: int, cfg: dict) -> float:
    """Pessimistic: ~9K input tokens per pair of arms (1K baseline + 8K hierarchical) and full maxTokens out."""
    gen = cfg["controlled_variables"]["generation"]
    p = gen["pricing_usd_per_1m_tokens"]
    per_q_in = 9000 / 2 * n_arms
    per_q_out = gen["inference_config"]["maxTokens"] * n_arms
    return len(questions) * (per_q_in * p["input"] + per_q_out * p["output"]) / 1e6


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--questions", nargs="+", help="question IDs, e.g. Q18 Q35 (default: all)")
    ap.add_argument("--arms", nargs="+", help="experiment keys (default: all)")
    ap.add_argument("--retrieval-only", action="store_true", help="Retrieve and score only; no model calls")
    ap.add_argument("--max-cost-usd", type=float, default=0.25)
    ap.add_argument("--profile", default="hrl-mfa")
    ap.add_argument("--region", default="us-west-2")
    ap.add_argument("--out-dir", default=str(ROOT / "results"))
    args = ap.parse_args(argv)

    cfg = load_config()
    gt = json.loads(GROUND_TRUTH_PATH.read_text())["questions"]
    questions = [q for q in gt if not args.questions or q["id"] in args.questions]
    if args.questions and len(questions) != len(set(args.questions)):
        sys.exit(f"unknown question IDs: {sorted(set(args.questions) - {q['id'] for q in questions})}")

    agent_rt, bedrock_rt, all_arms, ident = runner_clients(args.profile, args.region)
    arms = {k: v for k, v in all_arms.items() if not args.arms or k in args.arms}
    est = 0.0 if args.retrieval_only else estimate_cost(questions, len(arms), cfg)
    print(f"Identity: {ident}\nArms: {arms}\nQuestions: {len(questions)} | model calls: "
          f"{0 if args.retrieval_only else len(questions) * len(arms)} | pessimistic cost estimate: USD {est:.4f}")
    if est > args.max_cost_usd:
        sys.exit(f"STOP: estimate exceeds --max-cost-usd {args.max_cost_usd}")

    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ("-retrieval" if args.retrieval_only else "")
    out = Path(args.out_dir) / run_id
    out.mkdir(parents=True, exist_ok=False)
    gen = cfg["controlled_variables"]["generation"]
    meta = {"run_id": run_id, "identity": ident, "arms": arms, "model": gen["inference_profile_id"],
            "inference_config": gen["inference_config"], "prompt_template_version": gen["prompt_template_version"],
            "top_k": cfg["controlled_variables"]["retrieval"]["numberOfResults"],
            "config_fingerprint": config_fingerprint(cfg), "questions": [q["id"] for q in questions],
            "retrieval_only": args.retrieval_only}
    (out / "run_metadata.json").write_text(json.dumps(meta, indent=2))

    records, spent, stopped_reason = [], 0.0, None
    with open(out / "results.jsonl", "w") as fh:
        for q in questions:          # interleave arms per question (same conditions over time)
            for arm, kb_id in arms.items():
                rec = evaluate_one(q, arm, kb_id, cfg, agent_rt, bedrock_rt, args.retrieval_only)
                records.append(rec)
                fh.write(json.dumps(rec) + "\n")
                fh.flush()
                spent += rec.get("cost_usd", 0) or 0
                if spent > args.max_cost_usd:   # actual tracked cost guard
                    stopped_reason = f"actual tracked cost USD {spent:.6f} exceeded --max-cost-usd {args.max_cost_usd}"
                s = rec.get("scores", {})
                print(f"{q['id']:4s} {arm:22s} {rec['status']:14s} recall={rec.get('retrieval', {}).get('keyword_recall')}"
                      + ("" if args.retrieval_only else f" coverage={s.get('answer_keyword_coverage')} "
                         f"abstained={s.get('abstained')} cost=${rec.get('cost_usd', 0):.6f}")
                      + (f"  ERROR {rec['error']}" if rec["status"] == "error" else ""))
                if stopped_reason:
                    break
            if stopped_reason:
                break
    meta.update({"completed_items": len(records), "planned_items": len(questions) * len(arms),
                 "tracked_cost_usd": round(spent, 8), "stopped_early": stopped_reason})
    (out / "run_metadata.json").write_text(json.dumps(meta, indent=2))
    if stopped_reason:
        print(f"\nSTOPPED EARLY: {stopped_reason} after {len(records)} item(s)")
    summary = summarize(records)
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    (out / "summary.md").write_text(summary_markdown(summary, meta))
    print("\n" + summary_markdown(summary, meta))
    try:   # offline v2 rescoring (writes rescored_v2.* next to the originals; no AWS calls)
        import rescore_results
        rescore_results.main(["--results-dir", str(out.parent), "--run", out.name])
    except Exception as e:  # rescoring must never invalidate a completed run
        print(f"v2 rescoring skipped: {type(e).__name__}: {e}")
    print(f"Results: {out}")
    return 0 if all(r["status"] != "error" for r in records) and not stopped_reason else 1


if __name__ == "__main__":
    sys.exit(main())
