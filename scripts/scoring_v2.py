"""
Revised (v2) LEXICAL scoring for the RAG experiment. Pure functions, no AWS.

Changes vs v1 (scripts/run_evaluation.py, kept unchanged for comparison):
1. Token-sequence matching instead of raw substring matching:
   - tolerated : case, whitespace, hyphen vs space ("30-second" == "30 second"), unicode dashes,
                 thousands separators ("18,240" == "18240"), unit plurals ("1 hour" == "1 hours")
   - NOT tolerated (different facts): other digits or identifiers ("400" != "4000", "us-west-2" != "us-west-1",
                 "10.66.0.0/20" != "10.66.16.0/20", "7 days" != "17 days"); token order; missing tokens.
   - also fixes a v1 false positive class: v1 substring "400" matched inside "4000".
2. Required facts: questions listed in data/evaluation/scoring_revisions.json are scored on the facts the
   question actually asks for (documented rationale); all others use ground-truth answer_keywords as-is.
3. Citation parsing accepts "[S1, Section 9]", "[S1, S3]", "[S1][S2]"; any extra text inside the brackets
   is recorded. ID validity is reported separately from (lexical) cited-chunk support.
Nothing here verifies SEMANTIC support - that would need human review or an LLM judge.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

SCORING_VERSION = "v2"
ROOT = Path(__file__).resolve().parent.parent
REVISIONS_PATH = ROOT / "data" / "evaluation" / "scoring_revisions.json"

_DASHES = dict.fromkeys(map(ord, "‐‑‒–—−"), "-")
# A token is a run of letters/digits that may contain '.', '/', ':' between alphanumerics (IPs, CIDRs, ARNs-ish).
_TOKEN = re.compile(r"[a-z0-9]+(?:[./:][a-z0-9]+)*")
_UNIT_PLURALS = {"seconds": "second", "minutes": "minute", "hours": "hour", "days": "day", "messages": "message",
                 "tokens": "token", "years": "year", "months": "month", "weeks": "week"}


def tokens(text: str) -> list[str]:
    t = (text or "").translate(_DASHES).lower()
    t = re.sub(r"(?<=\d),(?=\d{3}\b)", "", t)         # 18,240 -> 18240 (thousands separators only)
    t = t.replace("-", " ").replace("_", " ")         # hyphen/underscore == space (formatting, not meaning)
    return [_UNIT_PLURALS.get(w, w) for w in _TOKEN.findall(t)]


def contains_fact(text: str, fact: str) -> bool:
    """True if the fact's token sequence appears contiguously, on token boundaries, in text."""
    hay, needle = tokens(text), tokens(fact)
    if not needle:
        return False
    n = len(needle)
    return any(hay[i:i + n] == needle for i in range(len(hay) - n + 1))


def load_revisions(path: Path = REVISIONS_PATH) -> dict:
    data = json.loads(path.read_text())
    data["_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    return data


def required_facts(q: dict, revisions: dict) -> tuple[list[str], str]:
    rev = revisions.get("required_keywords", {}).get(q["id"])
    if rev:
        unknown = [k for k in rev["required"] if k not in q["answer_keywords"]]
        if unknown:
            raise ValueError(f"{q['id']}: revised required facts must be a subset of answer_keywords: {unknown}")
        return list(rev["required"]), "revised"
    return list(q["answer_keywords"]), "ground_truth"


_BRACKET = re.compile(r"\[([^\[\]]{1,80})\]")
_SID = re.compile(r"\bS(\d{1,2})\b")


def parse_citations(answer: str) -> dict:
    """Source IDs from bracket groups that contain at least one S<n>; extra bracket text is kept, not trusted."""
    ids, extras = set(), []
    for grp in _BRACKET.findall(answer or ""):
        found = _SID.findall(grp)
        if not found:
            continue
        ids.update(int(x) for x in found)
        rest = _SID.sub("", grp).strip(" ,;-")
        if rest:
            extras.append(rest)
    return {"cited_ids": sorted(ids), "extra_citation_text": extras}


def score_answer_v2(q: dict, answer: str, abstain_text: str, stop_reason: str | None,
                    revisions: dict, chunk_texts: list[str] | None, num_sources: int) -> dict:
    """
    chunk_texts: full retrieved chunk texts in [S#] order, or None when the run did not store them
    (then text-dependent metrics are None - never estimated from previews).
    """
    unanswerable = q["question_type"] == "unanswerable"
    facts, facts_source = required_facts(q, revisions)
    matched = [f for f in facts if contains_fact(answer, f)]
    abstained = contains_fact(answer, abstain_text.rstrip("."))
    cit = parse_citations(answer)
    ids_valid = all(1 <= i <= num_sources for i in cit["cited_ids"]) if cit["cited_ids"] else None
    cited_support = retrieved_recall = None
    if chunk_texts is not None and not unanswerable:
        cited = " ".join(chunk_texts[i - 1] for i in cit["cited_ids"] if 1 <= i <= len(chunk_texts))
        if matched and cit["cited_ids"]:
            cited_support = round(sum(contains_fact(cited, f) for f in matched) / len(matched), 3)
        ctx = " ".join(chunk_texts)
        retrieved_recall = round(sum(contains_fact(ctx, f) for f in facts) / len(facts), 3) if facts else None
    coverage = round(len(matched) / len(facts), 3) if facts and not unanswerable else None
    return {
        "scoring_version": SCORING_VERSION,
        "required_facts": facts, "required_facts_source": facts_source,
        "matched_facts": matched, "missing_facts": [f for f in facts if f not in matched],
        "answer_fact_coverage": coverage,
        "all_required_facts_matched": None if unanswerable else coverage == 1.0,
        "abstained": abstained,
        "abstention_correct": abstained if unanswerable else None,
        "false_abstention": None if unanswerable else abstained,
        "cited_ids": cit["cited_ids"], "extra_citation_text": cit["extra_citation_text"],
        "citation_id_validity": ids_valid,                    # IDs exist in context - NOT factual support
        "cited_chunk_fact_support": cited_support,           # lexical; None if chunk text not stored
        "retrieved_fact_recall": retrieved_recall,           # lexical; None if chunk text not stored
        "truncated": stop_reason == "max_tokens",
    }


def classify_failure(record: dict, v2: dict) -> dict:
    """
    Automated LEXICAL triage of where an answer went wrong.
      retrieval  : required evidence not fully retrieved (passage evidence < 90% for some expected source)
      generation : evidence retrieved, but answer misses required facts / abstains
    Uses v1 passage-evidence data stored by the run (computed on full chunk text at run time).
    """
    if record.get("question_type") == "unanswerable":
        return {"evidence": "n/a", "answer": "abstained" if v2["abstained"] else "answered",
                "failure_type": "none" if v2["abstained"] else "generation"}
    ret = record.get("retrieval", {}) or {}
    present = ret.get("all_passages_present")
    cov = ret.get("passage_evidence_coverage")
    evidence = ("complete" if present else "partial" if (cov or 0) >= 0.3 else "missing") if present is not None else "unknown"
    if v2["all_required_facts_matched"]:
        answer = "correct (lexical)"
    elif v2["abstained"]:
        answer = "abstained"
    elif v2["matched_facts"]:
        answer = "partial"
    else:
        answer = "facts missing"
    if answer == "correct (lexical)":
        ftype = "none"
    elif evidence == "complete":
        ftype = "generation"
    elif evidence in ("partial", "missing"):
        ftype = "retrieval"
    else:
        ftype = "unknown"
    return {"evidence": evidence, "answer": answer, "failure_type": ftype}
