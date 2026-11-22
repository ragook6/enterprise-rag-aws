"""
results-public/ must be a faithful, sanitized copy of results/.
- Always: only placeholder identifiers; no 12-digit account ID except the AWS documentation example; no request IDs.
- When the private originals exist (local machine only): every non-identifier field is identical.
"""
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "docs"))
import export_public_results as exp  # noqa: E402

PUBLIC, PRIVATE = ROOT / "results-public", ROOT / "results"
FICTIONAL_ACCOUNT_IDS = {  # invented accounts inside the synthetic HRL documents (scripts/content.py)
    "604318275519", "739204615882", "812475930164", "357120894463", "290563718845", "538946102277", "671829350418"}


class PublicCopyTests(unittest.TestCase):
    def test_only_placeholder_identifiers(self):
        for run in PUBLIC.iterdir():
            meta = json.loads((run / "run_metadata.json").read_text())
            self.assertEqual(set(meta["arms"].values()), {"KBFIXED001", "KBHIER0001"})
            self.assertIn(":111122223333:", meta["identity"])
            for line in (run / "results.jsonl").read_text().splitlines():
                r = json.loads(line)
                self.assertIn(r["knowledge_base_id"], {"KBFIXED001", "KBHIER0001"})
                self.assertIsNone(r.get("request_id"))
            blob = " ".join(p.read_text() for p in run.iterdir())
            accounts = set(re.findall(r"(?<![0-9])[0-9]{12}(?![0-9])", blob)) - {"111122223333"} - FICTIONAL_ACCOUNT_IDS
            self.assertEqual(accounts, set(), f"unexpected 12-digit IDs in {run.name}")

    @unittest.skipUnless(PRIVATE.is_dir(), "private originals not present (public clone)")
    def test_identical_to_private_originals_except_identifiers(self):
        for run in PUBLIC.iterdir():
            for f in ("results.jsonl", "rescored_v2.jsonl"):
                orig = [json.loads(l) for l in (PRIVATE / run.name / f).read_text().splitlines() if l.strip()]
                pub = [json.loads(l) for l in (run / f).read_text().splitlines() if l.strip()]
                self.assertEqual([exp.strip_identifiers(r) for r in orig], [exp.strip_identifiers(r) for r in pub], f)
            for f in ("summary.json", "rescored_v2_summary.json"):
                self.assertEqual(json.loads((PRIVATE / run.name / f).read_text()), json.loads((run / f).read_text()), f)


if __name__ == "__main__":
    unittest.main(verbosity=2)
