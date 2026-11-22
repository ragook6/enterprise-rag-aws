"""
Tests for the read-only dashboard (app/results_loader.py, app/dashboard.py). No AWS, no network.
Run:  .venv/bin/python -m unittest discover -s tests -v
"""
import ast
import os
import json
import shutil
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
os.environ["RAG_RESULTS_DIR"] = str(ROOT / "results-public")   # tests use the sanitized, publishable copy
import results_loader as rl  # noqa: E402

LEGACY_RUN = "20261121T225932Z"


def current_record(arm, qid="Q18", status="ok", **over):
    rec = {"id": qid, "arm": arm, "knowledge_base_id": "KB", "question_type": "numeric", "difficulty": "easy",
           "question": "q?", "expected_answer": "a", "status": status, "answer": "1024 MB [S1]", "stop_reason": "end_turn",
           "sources": [{"document": "Lambda_Incident_Runbook.pdf", "page": 1, "score": 0.9, "preview": "x"}],
           "retrieve_ms": 500, "generate_ms": 400, "generate_wall_ms": 450, "input_tokens": 1000, "output_tokens": 50,
           "cost_usd": 0.00004,
           "retrieval": {"keyword_recall": 1.0, "source_doc_hit": True, "source_page_label_hit": 0.0,
                         "passage_evidence_coverage": 1.0, "all_passages_present": True,
                         "passages": [{"document": "Lambda_Incident_Runbook.pdf", "page": 2, "coverage": 1.0, "present": True}],
                         "retrieved_docs": ["Lambda_Incident_Runbook.pdf"], "num_chunks": 1, "context_chars": 100},
           "scores": {"abstained": False, "answer_keyword_coverage": 1.0, "fully_correct": True, "abstention_correct": None,
                      "false_abstention": False, "partial_answer_flagged": False, "cited_sources": [1],
                      "citation_id_validity": True, "cited_chunk_keyword_support": 1.0, "has_citation": True, "truncated": False}}
    rec.update(over)
    return rec


def write_run(base: Path, run_id: str, records, retrieval_only=False):
    d = base / run_id
    d.mkdir(parents=True)
    (d / "run_metadata.json").write_text(json.dumps({"run_id": run_id, "model": "us.amazon.nova-micro-v1:0",
                                                     "top_k": 5, "retrieval_only": retrieval_only}))
    (d / "results.jsonl").write_text("\n".join(json.dumps(r) for r in records) + "\n")


class LoaderTests(unittest.TestCase):
    def test_existing_q18_run_is_discovered_as_legacy(self):
        runs = {r.run_id: r for r in rl.discover_runs()}
        self.assertIn(LEGACY_RUN, runs)
        run = runs[LEGACY_RUN]
        self.assertEqual(run.schema, "legacy")
        self.assertEqual(run.question_ids, ["Q18"])
        hier = next(r for r in run.records if r["arm"] == "improved-hierarchical")
        self.assertEqual(hier["page_label_hit"], 0.0)            # legacy source_page_hit mapped, not altered
        self.assertIsNone(hier["passage_evidence_coverage"])     # not recorded -> None, never invented
        self.assertIsNone(hier["cited_chunk_keyword_support"])
        self.assertTrue(hier["citation_id_validity"])            # legacy citation_validity = ID validity
        s = rl.summarize_run(run)
        self.assertIsNone(s["improved-hierarchical"]["passage_evidence_coverage"])
        self.assertEqual(s["baseline-fixed100"]["fully_correct"], 1.0)
        self.assertEqual(rl.fmt(s["improved-hierarchical"]["passage_evidence_coverage"], "pct"), "N/A")

    def test_future_runs_auto_discovered_newest_first(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            write_run(tmp, "20261122T010000Z", [current_record("baseline-fixed100"), current_record("improved-hierarchical")])
            write_run(tmp, "20261122T020000Z-retrieval", [current_record("baseline-fixed100", status="retrieval_only")],
                      retrieval_only=True)
            (tmp / "broken").mkdir(); (tmp / "broken" / "run_metadata.json").write_text("{not json")
            (tmp / "broken" / "results.jsonl").write_text("{}")
            (tmp / "notes").mkdir()
            runs = rl.discover_runs(tmp)
            self.assertEqual([r.run_id for r in runs], ["20261122T020000Z-retrieval", "20261122T010000Z"])
            self.assertTrue(runs[0].retrieval_only)
            self.assertEqual(runs[1].schema, "current")
            s = rl.summarize_run(runs[1])
            self.assertEqual(s["improved-hierarchical"]["passage_evidence_coverage"], 1.0)
            self.assertEqual(s["improved-hierarchical"]["page_label_hit"], 0.0)
        finally:
            shutil.rmtree(tmp)

    def test_errors_counted_and_excluded_from_means(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            err = {"id": "Q19", "arm": "baseline-fixed100", "status": "error", "error": "ThrottlingException",
                   "question_type": "numeric", "retrieval": {}, "scores": {}}
            write_run(tmp, "R1", [current_record("baseline-fixed100"), err])
            s = rl.summarize_run(rl.discover_runs(tmp)[0])["baseline-fixed100"]
            self.assertEqual((s["ok"], s["errors"]), (1, 1))
            self.assertEqual(s["fully_correct"], 1.0)
        finally:
            shutil.rmtree(tmp)

    def test_fmt_never_invents(self):
        self.assertEqual(rl.fmt(None), "N/A"); self.assertEqual(rl.fmt(None, "usd"), "N/A")
        self.assertEqual(rl.fmt(0.5, "pct"), "50%"); self.assertEqual(rl.fmt(True), "yes")

    def test_arm_identity_fixed(self):
        self.assertEqual([a["color"] for a in rl.ARMS.values()], ["#2a78d6", "#eb6834"])


class ReadOnlyTests(unittest.TestCase):
    FORBIDDEN = {"boto3", "botocore", "anthropic", "requests", "httpx", "httpx2", "urllib3", "aiohttp"}

    def test_app_imports_no_aws_or_http_clients(self):
        for f in (ROOT / "app").glob("*.py"):
            tree = ast.parse(f.read_text())
            mods = {n.names[0].name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)}
            mods |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
            self.assertFalse(mods & self.FORBIDDEN, f"{f.name} imports {mods & self.FORBIDDEN}")


class DashboardRenderTests(unittest.TestCase):
    def _render(self):
        from streamlit.testing.v1 import AppTest
        return AppTest.from_file(str(ROOT / "app" / "dashboard.py"), default_timeout=60)

    def test_renders_offline_with_aws_blocked(self):
        def no_network(*a, **k):
            raise AssertionError("dashboard attempted a network connection")
        blocked = {m: None for m in ("boto3", "botocore", "anthropic")}   # import -> ImportError
        with mock.patch.dict(sys.modules, blocked), mock.patch.object(socket.socket, "connect", no_network):
            at = self._render().run()
            self.assertFalse(at.exception, [e.value for e in at.exception])
            text = self._text(at)
            for phrase in ("Read-only dashboard", "not semantically verified", "Original (v1) vs revised (v2)",
                           "Retrieval vs generation failures"):
                self.assertIn(phrase, text)
            fail_tables = [d.value for d in at.dataframe if "Reviewer reading (semantic, not verified)" in d.value.columns]
            self.assertEqual(len(fail_tables), 1)
            ft = fail_tables[0]
            self.assertEqual(sorted(set(ft["Q"])), ["Q03", "Q15", "Q22", "Q30", "Q31", "Q34"])
            self.assertIn("Automated failure type", ft.columns)
            self.assertNotIn("N/A", set(ft["Reviewer: failure type"]))
            self.assertIn("20261121T231031Z", at.sidebar.selectbox[0].value)          # newest run by default
            # switch to the legacy Q18 run: legacy banner + N/A, no crash
            at.sidebar.selectbox[0].select(LEGACY_RUN).run()
            self.assertFalse(at.exception, [e.value for e in at.exception])
            text = self._text(at)
            self.assertIn("Legacy metrics", text); self.assertIn("N/A", text); self.assertIn("1024 MB", text)
            self.assertEqual(at.sidebar.selectbox[1].value, "Q18")

    @staticmethod
    def _text(at):
        return " ".join(x.value for coll in (at.markdown, at.warning, at.info, at.caption, at.subheader) for x in coll)

    def test_v2_and_failure_analysis_loaded(self):
        run = {r.run_id: r for r in rl.discover_runs()}["20261121T231031Z"]
        self.assertTrue(run.has_v2)
        self.assertEqual(run.v2_summary["baseline-fixed100"]["changed_vs_v1"], ["Q18"])
        self.assertIn("Q34", run.failure_analysis["questions"])
        legacy = {r.run_id: r for r in rl.discover_runs()}[LEGACY_RUN]
        self.assertEqual(legacy.failure_analysis, {})          # no reviewer file -> empty, not invented


if __name__ == "__main__":
    unittest.main(verbosity=2)
