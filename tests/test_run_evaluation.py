"""
Offline tests for scripts/run_evaluation.py - NO AWS calls.

botocore's Stubber intercepts the clients before any HTTP request, validates every request
AND every canned response against the real Bedrock API models, and fails on unexpected calls.
Run:  .venv/bin/python -m unittest discover -s tests -v
"""
import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import boto3
from botocore.stub import Stubber

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import run_evaluation as rev  # noqa: E402

CFG = rev.load_config()
GEN = CFG["controlled_variables"]["generation"]
TOPK = CFG["controlled_variables"]["retrieval"]["numberOfResults"]
GT = {q["id"]: q for q in json.loads(rev.GROUND_TRUTH_PATH.read_text())["questions"]}
ABSTAIN = GEN["abstain_text"]


def offline_client(service):
    # Fake credentials + Stubber: any un-stubbed call raises instead of reaching AWS.
    return boto3.client(service, region_name="us-west-2", aws_access_key_id="AKIDOFFLINE",
                        aws_secret_access_key="offline", aws_session_token="offline")


def retrieve_response(chunks):
    return {"retrievalResults": [
        {"content": {"text": c["text"], "type": "TEXT"},
         "location": {"type": "S3", "s3Location": {"uri": f"s3://hrl-rag-docs/documents/{c['doc']}"}},
         "score": c.get("score", 0.8),
         "metadata": ({"x-amz-bedrock-kb-document-page-number": float(c["page"])} if c.get("page") else {})}
        for c in chunks]}


def converse_response(text, stop="end_turn", tin=900, tout=40):
    return {"output": {"message": {"role": "assistant", "content": [{"text": text}]}},
            "stopReason": stop, "usage": {"inputTokens": tin, "outputTokens": tout, "totalTokens": tin + tout},
            "metrics": {"latencyMs": 321}}


def expected_retrieve_params(kb, question):
    return {"knowledgeBaseId": kb, "retrievalQuery": {"text": question},
            "retrievalConfiguration": {"vectorSearchConfiguration": {"numberOfResults": TOPK,
                                                                     "overrideSearchType": "SEMANTIC"}}}


def expected_converse_params(user_message):
    return {"modelId": "us.amazon.nova-micro-v1:0", "system": [{"text": GEN["system_prompt"]}],
            "messages": [{"role": "user", "content": [{"text": user_message}]}],
            "inferenceConfig": {"temperature": 0, "maxTokens": 512}}


Q18_CHUNK = {"doc": "Lambda_Incident_Runbook.pdf", "page": 2, "score": 0.86,
             "text": "The function hrl-prod-order-ingest is configured with 1024 MB of memory, "
                     "a 30 second timeout and a reserved concurrency of 400."}


class ConfigTests(unittest.TestCase):
    def test_generation_settings_match_approval(self):
        self.assertEqual(GEN["inference_profile_id"], "us.amazon.nova-micro-v1:0")
        self.assertEqual(GEN["inference_config"], {"temperature": 0, "maxTokens": 512})
        self.assertEqual(TOPK, 5)
        self.assertIn(ABSTAIN, GEN["system_prompt"])

    def test_fingerprint_stable_and_sensitive(self):
        fp = rev.config_fingerprint(CFG)
        self.assertEqual(fp, rev.config_fingerprint(copy.deepcopy(CFG)))
        changed = copy.deepcopy(CFG)
        changed["controlled_variables"]["generation"]["inference_config"]["temperature"] = 0.5
        self.assertNotEqual(fp, rev.config_fingerprint(changed))

    def test_bad_config_rejected(self):
        bad = copy.deepcopy(CFG)
        bad["controlled_variables"]["generation"]["abstain_text"] = "something else"
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(bad, fh)
        with self.assertRaises(ValueError):
            rev.load_config(Path(fh.name))
        os.unlink(fh.name)

    def test_cost_estimate_for_full_run_is_under_cap(self):
        est = rev.estimate_cost(list(GT.values()), 2, CFG)
        self.assertLess(est, 0.25)
        print(f"\n   pessimistic estimate for 35 questions x 2 arms: USD {est:.4f}")


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.agent, self.bed = offline_client("bedrock-agent-runtime"), offline_client("bedrock-runtime")
        self.sa, self.sb = Stubber(self.agent), Stubber(self.bed)
        self.sa.activate(); self.sb.activate()

    def tearDown(self):
        self.sa.assert_no_pending_responses(); self.sb.assert_no_pending_responses()
        self.sa.deactivate(); self.sb.deactivate()

    def run_one(self, qid, chunks, answer=None, arm="baseline-fixed100", kb="KBTESTAAAA", stop="end_turn", **kw):
        q = GT[qid]
        self.sa.add_response("retrieve", retrieve_response(chunks), expected_retrieve_params(kb, q["question"]))
        if answer is not None:
            parsed = [{"text": c["text"], "document": c["doc"], "page": c.get("page"), "score": c.get("score", 0.8)}
                      for c in chunks]
            self.sb.add_response("converse", converse_response(answer, stop),
                                 expected_converse_params(rev.build_user_message(q["question"], parsed)))
        return rev.evaluate_one(q, arm, kb, CFG, self.agent, self.bed, **{"retrieval_only": False, **kw})

    def test_answerable_correct_with_citation(self):
        r = self.run_one("Q18", [Q18_CHUNK], "1024 MB of memory, a 30 second timeout and reserved concurrency of 400 [S1].")
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["retrieval"]["keyword_recall"], 1.0)
        self.assertTrue(r["retrieval"]["source_doc_hit"])
        self.assertEqual(r["retrieval"]["source_page_label_hit"], 1.0)  # Q18 passage is on page 2
        self.assertEqual(r["scores"]["answer_keyword_coverage"], 1.0)
        self.assertTrue(r["scores"]["fully_correct"])
        self.assertEqual(r["scores"]["cited_sources"], [1])
        self.assertTrue(r["scores"]["citation_id_validity"])
        self.assertAlmostEqual(r["cost_usd"], (900 * 0.035 + 40 * 0.14) / 1e6, places=10)
        self.assertEqual(r["sources"][0]["document"], "Lambda_Incident_Runbook.pdf")

    def test_unanswerable_abstains(self):
        r = self.run_one("Q35", [Q18_CHUNK], ABSTAIN)
        self.assertTrue(r["scores"]["abstention_correct"])
        self.assertIsNone(r["scores"]["fully_correct"])

    def test_false_abstention_detected(self):
        r = self.run_one("Q18", [Q18_CHUNK], ABSTAIN)
        self.assertTrue(r["scores"]["false_abstention"])
        self.assertFalse(r["scores"]["fully_correct"])

    def test_partial_answer_flagged(self):
        r = self.run_one("Q30", [Q18_CHUNK], "The function runs in vpc-prod-orders-use2 [S1]. Not covered: the CIDR.")
        self.assertTrue(r["scores"]["partial_answer_flagged"])
        self.assertFalse(r["scores"]["fully_correct"])
        self.assertFalse(r["retrieval"]["source_doc_hit"])  # Transit_Gateway_Design.pdf not retrieved

    def test_empty_retrieval_abstains_without_model_call(self):
        r = self.run_one("Q18", [], answer=None)   # no converse stubbed -> a model call would fail the test
        self.assertEqual(r["stop_reason"], "no_context")
        self.assertTrue(r["scores"]["abstained"])
        self.assertEqual(r["cost_usd"], 0.0)

    def test_truncation_and_invalid_citation_flagged(self):
        r = self.run_one("Q18", [Q18_CHUNK], "1024 MB [S9]", stop="max_tokens")
        self.assertTrue(r["scores"]["truncated"])
        self.assertFalse(r["scores"]["citation_id_validity"])

    def test_aws_error_recorded_not_fabricated(self):
        self.sa.add_client_error("retrieve", service_error_code="ThrottlingException", http_status_code=429)
        r = rev.evaluate_one(GT["Q18"], "baseline-fixed100", "KBTESTAAAA", CFG, self.agent, self.bed, False)
        self.assertEqual(r["status"], "error")
        self.assertIn("ThrottlingException", r["error"])
        self.assertNotIn("answer", r)

    def test_retrieval_only_makes_no_model_call(self):
        q = GT["Q19"]
        self.sa.add_response("retrieve", retrieve_response([Q18_CHUNK]), expected_retrieve_params("KBTESTAAAA", q["question"]))
        r = rev.evaluate_one(q, "baseline-fixed100", "KBTESTAAAA", CFG, self.agent, self.bed, True)
        self.assertEqual(r["status"], "retrieval_only")
        self.assertNotIn("answer", r)

    def test_both_arms_send_identical_generation_settings(self):
        # Same question + same chunks to both KBs must produce byte-identical Converse requests;
        # Stubber asserts the exact parameters for each call.
        for arm, kb in (("baseline-fixed100", "KBFIXED001"), ("improved-hierarchical", "KBHIER0001")):
            r = self.run_one("Q18", [Q18_CHUNK], "1024 MB, 30 second, 400 [S1]", arm=arm, kb=kb)
            self.assertEqual(r["status"], "ok")


class SummaryAndGuardTests(unittest.TestCase):
    def test_summary_and_markdown(self):
        recs = []
        for arm in ("baseline-fixed100", "improved-hierarchical"):
            for qid, ans in (("Q18", "1024 MB, 30 second, 400 [S1]"), ("Q35", ABSTAIN)):
                q = GT[qid]
                chunks = [{"text": Q18_CHUNK["text"], "document": Q18_CHUNK["doc"], "page": 2, "score": 0.9}]
                recs.append({"id": qid, "arm": arm, "question_type": q["question_type"], "status": "ok",
                             "retrieval": rev.score_retrieval(q, chunks),
                             "scores": rev.score_answer(q, ans, ABSTAIN, chunks, "end_turn"),
                             "input_tokens": 900, "output_tokens": 30, "cost_usd": 0.00004,
                             "retrieve_ms": 200, "generate_ms": 400})
        s = rev.summarize(recs)
        self.assertEqual(s["baseline-fixed100"]["fully_correct_rate"], 1.0)
        self.assertEqual(s["baseline-fixed100"]["abstention_correct"], [True])
        md = rev.summary_markdown(s, {"run_id": "test", "model": "us.amazon.nova-micro-v1:0", "top_k": 5,
                                      "config_fingerprint": "x"})
        self.assertIn("| Answer: all expected facts matched [string match] | 1.0 | 1.0 |", md)
        self.assertIn("| Retrieval: page-label hit@k [informational only] |", md)
        self.assertIn("## Metric notes", md)

    def test_refuses_api_key_env(self):
        with mock.patch.dict(os.environ, {"AWS_BEARER_TOKEN_BEDROCK": "x"}):
            with self.assertRaises(SystemExit):
                rev.runner_clients("hrl-mfa", "us-west-2")



Q18_PASSAGE = [s for s in GT["Q18"]["sources"]][0]["passage"]
PAGE1_TEXT = ("HALCYON RIDGE LOGISTICS, INC. Lambda Incident Runbook Order Event Processor (hrl-prod-order-ingest) "
              "The Order Event Processor (OEP) ingests shipment order events from partner carriers.")


def chunk(text, doc="Lambda_Incident_Runbook.pdf", page=2, score=0.8):
    return {"text": text, "document": doc, "page": page, "score": score}


class EvidenceMetricTests(unittest.TestCase):
    def test_q18_hierarchical_page_label_regression(self):
        # Parent chunk starts on page 1 but contains the page-2 passage (what the live Q18 run showed).
        parent = chunk(PAGE1_TEXT + " " + Q18_PASSAGE + " The SQS queue visibility timeout is 180 seconds.", page=1)
        r = rev.score_retrieval(GT["Q18"], [parent])
        self.assertEqual(r["source_page_label_hit"], 0.0)          # page label misses (informational)
        self.assertEqual(r["passage_evidence_coverage"], 1.0)      # evidence is actually there
        self.assertTrue(r["all_passages_present"])
        self.assertEqual(r["keyword_recall"], 1.0)

    def test_passage_split_across_small_chunks_still_counts(self):
        words = Q18_PASSAGE.split(); half = len(words) // 2
        r = rev.score_retrieval(GT["Q18"], [chunk(" ".join(words[:half]), page=2),
                                            chunk(" ".join(words[half:]), page=2)])
        self.assertEqual(r["passage_evidence_coverage"], 1.0)
        self.assertEqual(r["source_page_label_hit"], 1.0)

    def test_passage_text_from_wrong_document_not_credited(self):
        r = rev.score_retrieval(GT["Q18"], [chunk(Q18_PASSAGE, doc="IAM_Security_Policies.pdf")])
        self.assertEqual(r["passage_evidence_coverage"], 0.0)
        self.assertFalse(r["all_passages_present"])

    def test_multi_hop_partial_evidence(self):
        q = GT["Q30"]   # needs Runbook + Transit Gateway passages
        rb = [s for s in q["sources"] if s["document"] == "Lambda_Incident_Runbook.pdf"][0]["passage"]
        r = rev.score_retrieval(q, [chunk(rb, page=1)])
        self.assertAlmostEqual(r["passage_evidence_coverage"], 0.5, places=2)
        self.assertFalse(r["all_passages_present"])
        self.assertEqual([p["present"] for p in r["passages"]], [True, False])

    def test_unanswerable_has_no_passage_metric(self):
        r = rev.score_retrieval(GT["Q35"], [chunk(Q18_PASSAGE)])
        self.assertIsNone(r["passage_evidence_coverage"]); self.assertIsNone(r["all_passages_present"])

    def test_identifiers_tokenized_intact(self):
        self.assertIn("10.66.0.0/20", rev.content_tokens("vpc-prod-orders-use2 (10.66.0.0/20) belongs"))
        self.assertIn("hrl-prod-order-ingest", rev.content_tokens("function hrl-prod-order-ingest."))
        self.assertNotIn("the", rev.content_tokens("the function"))

    def test_citation_id_validity_is_not_factual_support(self):
        chunks = [chunk("Unrelated text about DLQ redrive."), chunk(Q18_PASSAGE)]
        ans = "1024 MB of memory, a 30 second timeout and reserved concurrency of 400 [S1]."   # cites wrong chunk
        s = rev.score_answer(GT["Q18"], ans, ABSTAIN, chunks, "end_turn")
        self.assertTrue(s["citation_id_validity"])                 # ID exists...
        self.assertEqual(s["cited_chunk_keyword_support"], 0.0)    # ...but cited text lacks the facts
        s2 = rev.score_answer(GT["Q18"], ans.replace("[S1]", "[S2]"), ABSTAIN, chunks, "end_turn")
        self.assertEqual(s2["cited_chunk_keyword_support"], 1.0)

    def test_scoring_is_identical_for_both_arms(self):
        # Scoring functions take no arm input; identical evidence must give identical scores.
        chunks = [chunk(Q18_PASSAGE)]
        a = (rev.score_retrieval(GT["Q18"], chunks), rev.score_answer(GT["Q18"], "1024 MB 30 second 400 [S1]", ABSTAIN, chunks, "end_turn"))
        b = (rev.score_retrieval(GT["Q18"], copy.deepcopy(chunks)), rev.score_answer(GT["Q18"], "1024 MB 30 second 400 [S1]", ABSTAIN, copy.deepcopy(chunks), "end_turn"))
        self.assertEqual(a, b)
        import inspect
        for fn in (rev.score_retrieval, rev.score_answer, rev.passage_evidence):
            self.assertNotIn("arm", inspect.signature(fn).parameters)

    def test_markdown_documents_limitations(self):
        md = rev.summary_markdown({}, {"run_id": "t", "model": "m", "top_k": 5, "config_fingerprint": "x"})
        for phrase in ("Semantic support is NOT verified", "informational", "does **not** check"):
            self.assertIn(phrase, md)


class CostGuardTests(unittest.TestCase):
    def test_main_stops_when_actual_cost_exceeds_cap(self):
        calls = []
        def fake_eval(q, arm, kb, cfg, a, b, ro):
            calls.append((q["id"], arm))
            return {"id": q["id"], "arm": arm, "question_type": q["question_type"], "status": "ok", "cost_usd": 0.01,
                    "retrieval": rev.score_retrieval(q, []), "scores": rev.score_answer(q, "x", ABSTAIN, [], "end_turn")}
        tmp = tempfile.mkdtemp()
        with mock.patch.object(rev, "runner_clients", return_value=(None, None, {"a1": "K1", "a2": "K2"}, "test-identity")), \
             mock.patch.object(rev, "evaluate_one", side_effect=fake_eval), mock.patch("builtins.print"):
            rc = rev.main(["--max-cost-usd", "0.025", "--out-dir", tmp, "--questions", "Q01", "Q02", "Q03"])
        self.assertEqual(rc, 1)
        self.assertEqual(len(calls), 3)          # 0.01+0.01 <= 0.025, third call pushes 0.03 > cap -> stop
        run_dir = next(Path(tmp).iterdir())
        meta = json.loads((run_dir / "run_metadata.json").read_text())
        self.assertEqual((meta["completed_items"], meta["planned_items"]), (3, 6))
        self.assertIn("exceeded", meta["stopped_early"])
        self.assertEqual(len((run_dir / "results.jsonl").read_text().splitlines()), 3)

if __name__ == "__main__":
    unittest.main(verbosity=2)
