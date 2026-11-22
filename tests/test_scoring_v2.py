"""
Tests for v2 lexical scoring, citation parsing, rescoring and failure triage. Offline; no AWS.
Includes regression tests on the stored answers of run 20261121T231031Z (Q18, Q30, Q31, and the guard cases).
"""
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import rescore_results  # noqa: E402
import scoring_v2 as v2  # noqa: E402

RUN = "20261121T231031Z"
RUN_DIR = ROOT / "results-public" / RUN   # sanitized copy (identical answers/metrics)
GT = {q["id"]: q for q in json.loads((ROOT / "data/evaluation/ground_truth.json").read_text())["questions"]}
REV = v2.load_revisions()
ABSTAIN = "The provided documents do not contain this information."
STORED = {(r["id"], r["arm"]): r for r in map(json.loads, (RUN_DIR / "results.jsonl").read_text().splitlines())}
B, H = "baseline-fixed100", "improved-hierarchical"


def score(qid, arm):
    r = STORED[(qid, arm)]
    return v2.score_answer_v2(GT[qid], r["answer"], ABSTAIN, r["stop_reason"], REV, None, len(r["sources"]))


class MatchingTests(unittest.TestCase):
    def test_tolerated_formatting(self):
        for text, fact in [("30-second timeout", "30 second"), ("30 seconds", "30 second"), ("1,024 MB", "1024 MB"),
                           ("18240 messages", "18,240"), ("15–minute RPO", "15 minutes"), ("TGW-RT-PROD", "tgw-rt-prod"),
                           ("hrl backup tier1", "hrl-backup-tier1"), ("maxReceiveCount  of\n5", "maxReceiveCount of 5")]:
            self.assertTrue(v2.contains_fact(text, fact), (text, fact))

    def test_different_facts_rejected(self):
        for text, fact in [("concurrency of 4000", "400"), ("us-west-1", "us-west-2"), ("10.66.16.0/20", "10.66.0.0/20"),
                           ("10.66.0.0/2", "10.66.0.0/20"), ("17 days", "7 days"), ("within 24 hours", "7 days"),
                           ("hrl-backup-tier2", "hrl-backup-tier1"), ("timeout 300 seconds", "30 second"),
                           ("second 30", "30 second"), ("ASN 646200", "64620")]:
            self.assertFalse(v2.contains_fact(text, fact), (text, fact))

    def test_v1_substring_false_positive_fixed(self):
        self.assertIn("400", "4000")                       # what v1 effectively did
        self.assertFalse(v2.contains_fact("4000", "400"))  # v2 respects token boundaries


class CitationTests(unittest.TestCase):
    def test_formats(self):
        c = v2.parse_citations("a [S1, Section 9]. b [S2][S3] c [S1, S4] [Note] [12] d [s5]")
        self.assertEqual(c["cited_ids"], [1, 2, 3, 4])
        self.assertEqual(c["extra_citation_text"], ["Section 9"])

    def test_id_validity_separate_from_support(self):
        q = GT["Q18"]
        texts = ["DLQ redrive text", "1024 MB of memory, a 30 second timeout and a reserved concurrency of 400"]
        s = v2.score_answer_v2(q, "1024 MB, 30 second, 400 [S1]", ABSTAIN, "end_turn", REV, texts, 2)
        self.assertTrue(s["citation_id_validity"]); self.assertEqual(s["cited_chunk_fact_support"], 0.0)
        s = v2.score_answer_v2(q, "1024 MB, 30 second, 400 [S2, Section 4]", ABSTAIN, "end_turn", REV, texts, 2)
        self.assertEqual(s["cited_chunk_fact_support"], 1.0); self.assertEqual(s["extra_citation_text"], ["Section 4"])
        s = v2.score_answer_v2(q, "1024 MB [S7]", ABSTAIN, "end_turn", REV, texts, 2)
        self.assertFalse(s["citation_id_validity"])

    def test_no_chunk_text_means_na_not_estimate(self):
        s = score("Q18", H)
        self.assertIsNone(s["cited_chunk_fact_support"]); self.assertIsNone(s["retrieved_fact_recall"])


class RegressionStoredRunTests(unittest.TestCase):
    """Real answers from the 35-question run."""

    def test_q18_fixed_hyphenation_now_correct(self):
        self.assertIn("30-second", STORED[("Q18", B)]["answer"])
        self.assertFalse(STORED[("Q18", B)]["scores"]["fully_correct"])        # v1 (preserved)
        self.assertTrue(score("Q18", B)["all_required_facts_matched"])          # v2

    def test_q30_hierarchical_scored_on_requested_facts(self):
        self.assertFalse(STORED[("Q30", H)]["scores"]["fully_correct"])
        s = score("Q30", H)
        self.assertEqual(s["required_facts_source"], "revised")
        self.assertEqual(s["required_facts"], ["10.66.0.0/20", "tgw-rt-prod"])
        self.assertTrue(s["all_required_facts_matched"])

    def test_q31_hierarchical_scored_on_requested_facts(self):
        self.assertFalse(STORED[("Q31", H)]["scores"]["fully_correct"])
        self.assertTrue(score("Q31", H)["all_required_facts_matched"])

    def test_revision_does_not_rescue_genuinely_incomplete_answers(self):
        s = score("Q31", B)                                # missing backup plan name
        self.assertFalse(s["all_required_facts_matched"]); self.assertEqual(s["missing_facts"], ["hrl-backup-tier1"])
        self.assertFalse(score("Q30", B)["all_required_facts_matched"])   # abstained
        self.assertTrue(score("Q30", B)["abstained"])

    def test_wrong_facts_stay_wrong(self):
        self.assertFalse(score("Q15", H)["all_required_facts_matched"])   # "24 hours" vs 7 days
        self.assertEqual(score("Q15", H)["missing_facts"], ["7 days"])
        self.assertFalse(score("Q34", B)["all_required_facts_matched"])   # invented gateway name
        self.assertFalse(score("Q22", H)["all_required_facts_matched"]); self.assertTrue(score("Q22", H)["false_abstention"])
        self.assertFalse(score("Q03", B)["all_required_facts_matched"])

    def test_section_citation_now_parsed(self):
        r = STORED[("Q21", H)]
        self.assertIn("[S1, Section 9]", r["answer"]); self.assertEqual(r["scores"]["cited_sources"], [])
        self.assertEqual(score("Q21", H)["cited_ids"], [1])

    def test_only_intended_questions_changed(self):
        changed = sorted((q, a) for (q, a), r in STORED.items()
                         if r["status"] == "ok" and r["scores"]["fully_correct"] is not None
                         and r["scores"]["fully_correct"] != score(q, a)["all_required_facts_matched"])
        self.assertEqual(changed, [("Q18", B), ("Q30", H), ("Q31", H)])

    def test_revisions_are_subset_and_limited(self):
        self.assertEqual(sorted(REV["required_keywords"]), ["Q30", "Q31"])
        for qid, rv in REV["required_keywords"].items():
            self.assertTrue(set(rv["required"]) <= set(GT[qid]["answer_keywords"]))
            self.assertTrue(rv["rationale"])


class TriageTests(unittest.TestCase):
    EXPECTED = {("Q03", B): "retrieval", ("Q03", H): "none", ("Q15", B): "none", ("Q15", H): "generation",
                ("Q22", B): "none", ("Q22", H): "generation", ("Q30", B): "retrieval", ("Q30", H): "none",
                ("Q31", B): "retrieval", ("Q31", H): "none", ("Q34", B): "retrieval", ("Q34", H): "retrieval"}

    def test_automated_triage_for_focus_questions(self):
        for key, expected in self.EXPECTED.items():
            self.assertEqual(v2.classify_failure(STORED[key], score(*key))["failure_type"], expected, key)

    def test_reviewer_file_covers_focus_questions_and_is_labeled(self):
        fa = json.loads((ROOT / "data/evaluation" / f"failure_analysis_{RUN}.json").read_text())
        self.assertIn("Not a human", fa["reviewer"])
        self.assertEqual(sorted(fa["questions"]), ["Q03", "Q15", "Q22", "Q30", "Q31", "Q34"])
        for arms in fa["questions"].values():
            self.assertEqual(sorted(arms), [B, H])
        # where lexical triage cannot see an invented claim, the reviewer reading is the one that says so
        self.assertEqual(fa["questions"]["Q34"][B]["failure"], "retrieval + generation")


class RescoreToolTests(unittest.TestCase):
    def test_rescore_writes_new_files_and_preserves_originals(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            dst = tmp / RUN
            shutil.copytree(RUN_DIR, dst, ignore=shutil.ignore_patterns("rescored_v2*"))
            before = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in dst.iterdir()}
            rescore_results.main(["--results-dir", str(tmp), "--run", RUN])
            after = {f: hashlib.sha256((dst / f).read_bytes()).hexdigest() for f in before}
            self.assertEqual(before, after)
            for f in ("rescored_v2.jsonl", "rescored_v2_summary.json", "rescored_v2_metadata.json"):
                self.assertTrue((dst / f).is_file())
            s = json.loads((dst / "rescored_v2_summary.json").read_text())
            self.assertEqual(s[B]["changed_vs_v1"], ["Q18"]); self.assertEqual(s[H]["changed_vs_v1"], ["Q30", "Q31"])
            self.assertEqual(s[B]["v1_fully_correct"], 0.7647)          # original value carried unchanged
            rows = [json.loads(l) for l in (dst / "rescored_v2.jsonl").read_text().splitlines()]
            self.assertEqual(len(rows), 70)
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main(verbosity=2)
