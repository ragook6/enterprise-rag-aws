#!/usr/bin/env python3
"""
Validate the generated PDFs and ground_truth.json.

Checks:
  1. All five expected PDFs exist, have 4-6 pages, and match the recorded sha256.
  2. ground_truth.json has >= 20 questions, unique IDs and all required fields.
  3. Every source passage appears on the exact page recorded (re-extracted with pypdf).
  4. Every answer keyword appears in the answer and in at least one source passage.
  5. Unanswerable questions have no sources and their topic is absent from the corpus.
  6. Cross-references like "HRL-NET-002 section 8" point to a section that exists.
Exits non-zero on any failure.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).parent))
from content import DOCUMENTS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DOC_DIR = ROOT / "data" / "documents"
GT = ROOT / "data" / "evaluation" / "ground_truth.json"
EXPECTED = [d["filename"] for d in DOCUMENTS]
UNANSWERABLE_PROBES = {"Q35": ["Enterprise Support"]}

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)
    return cond


def norm(t):
    return re.sub(r"\s+", " ", t).strip()


def main():
    # 1. PDFs
    pages = {}
    for name in EXPECTED:
        path = DOC_DIR / name
        if not check(path.exists(), f"missing PDF {name}"):
            continue
        pages[name] = [norm(p.extract_text() or "") for p in PdfReader(str(path)).pages]
        check(4 <= len(pages[name]) <= 6, f"{name}: {len(pages[name])} pages (expected 4-6)")
        print(f"  {name:38s} {len(pages[name])} pages")

    # 2. Ground truth structure
    gt = json.loads(GT.read_text())
    qs = gt["questions"]
    check(len(qs) >= 20, f"only {len(qs)} questions")
    ids = [q["id"] for q in qs]
    check(len(ids) == len(set(ids)), "duplicate question IDs")
    for meta in gt["documents"]:
        digest = hashlib.sha256((DOC_DIR / meta["document"]).read_bytes()).hexdigest()
        check(digest == meta["sha256"], f"{meta['document']}: sha256 differs (rebuild ground truth)")

    corpus = " ".join(" ".join(p) for p in pages.values()).lower()
    for q in qs:
        for field in ("id", "question", "answer", "question_type", "difficulty", "answer_keywords", "sources"):
            check(field in q, f"{q.get('id')}: missing field {field}")
        # 3. passage on recorded page
        for s in q["sources"]:
            doc_pages = pages.get(s["document"], [])
            ok = 1 <= s["page"] <= len(doc_pages) and norm(s["passage"]) in doc_pages[s["page"] - 1]
            check(ok, f"{q['id']}: passage not on {s['document']} p.{s['page']}")
        # 4. keywords supported by answer and evidence
        evidence = " ".join(s["passage"] for s in q["sources"]).lower()
        for kw in q["answer_keywords"]:
            check(kw.lower() in q["answer"].lower(), f"{q['id']}: keyword {kw!r} not in answer")
            check(kw.lower() in evidence, f"{q['id']}: keyword {kw!r} not supported by passages")
        # 5. unanswerable
        if q["question_type"] == "unanswerable":
            check(not q["sources"], f"{q['id']}: unanswerable question has sources")
            for probe in UNANSWERABLE_PROBES.get(q["id"], []):
                check(probe.lower() not in corpus, f"{q['id']}: probe {probe!r} found in corpus")
        elif check(q["sources"], f"{q['id']}: no sources"):
            pass

    # 6. Cross-reference integrity
    sections = {d["doc_id"]: sum(1 for b in d["body"] if b[0] == "h1") for d in DOCUMENTS}
    pattern = re.compile(r"(HRL-[A-Z]{3}-\d{3}|SOW-HRL-2026-017)\s+sections?\s+(\d+)(?:\s+and\s+(\d+))?")
    xrefs = 0
    for d in DOCUMENTS:
        text = " ".join(b[1] if isinstance(b[1], str) else " ".join(map(str, b[1])) for b in d["body"] if len(b) > 1)
        for target, *nums in pattern.findall(text):
            for n in filter(None, nums):
                xrefs += 1
                check(int(n) <= sections[target], f"{d['doc_id']}: reference {target} section {n} does not exist")

    by_type = {}
    for q in qs:
        by_type[q["question_type"]] = by_type.get(q["question_type"], 0) + 1
    print(f"  questions: {len(qs)}  by type: {by_type}")
    print(f"  cross-document section references checked: {xrefs}")

    if failures:
        print("\nVALIDATION FAILED:")
        for f in failures:
            print("  -", f)
        sys.exit(1)
    print("\nVALIDATION PASSED")


if __name__ == "__main__":
    main()
