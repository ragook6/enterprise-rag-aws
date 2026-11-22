#!/usr/bin/env python3
"""
Create results-public/ - a sanitized, publishable copy of results/ (which stays private and unchanged).

    .venv/bin/python scripts/docs/export_public_results.py

Redactions (identifiers only - no metric, answer, source text or score is changed):
  - AWS account ID                       -> 111122223333 (AWS documentation example account)
  - Knowledge Base IDs (per arm)         -> KBFIXED001 / KBHIER0001
  - request_id values                    -> null
  - any value in the local, git-ignored .sensitive-denylist -> REDACTED (safety net)
Verification (fails loudly): every non-identifier field equals the original; no denylisted value remains;
original files are byte-identical before and after.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC, DST = ROOT / "results", ROOT / "results-public"
DENYLIST = ROOT / ".sensitive-denylist"
PLACEHOLDER_ACCOUNT = "111122223333"
KB_PLACEHOLDER = {"baseline-fixed100": "KBFIXED001", "improved-hierarchical": "KBHIER0001"}
IDENTIFIER_KEYS = {"knowledge_base_id", "request_id", "identity", "arms", "original_file_sha256"}
FILES = ("results.jsonl", "summary.json", "summary.md", "run_metadata.json",
         "rescored_v2.jsonl", "rescored_v2_summary.json", "rescored_v2_metadata.json")


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def build_mapping(run_dir: Path) -> dict[str, str]:
    meta = json.loads((run_dir / "run_metadata.json").read_text())
    mapping = {}
    account = meta.get("identity", "").split(":")[4] if meta.get("identity", "").count(":") >= 4 else None
    if account:
        mapping[account] = PLACEHOLDER_ACCOUNT
    for arm, kb in meta.get("arms", {}).items():
        mapping[kb] = KB_PLACEHOLDER.get(arm, "KBREDACTED")
    return mapping


def redact_text(text: str, mapping: dict[str, str], deny: list[str]) -> str:
    for real in sorted(mapping, key=len, reverse=True):
        text = text.replace(real, mapping[real])
    for real in deny:
        if real not in mapping:
            text = re.sub(re.escape(real), "REDACTED", text)
    return text


def redact_obj(obj, mapping, deny):
    if isinstance(obj, dict):
        return {k: (None if k == "request_id" else redact_obj(v, mapping, deny)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_obj(v, mapping, deny) for v in obj]
    if isinstance(obj, str):
        return redact_text(obj, mapping, deny)
    return obj


def strip_identifiers(obj):
    if isinstance(obj, dict):
        return {k: strip_identifiers(v) for k, v in obj.items() if k not in IDENTIFIER_KEYS}
    if isinstance(obj, list):
        return [strip_identifiers(v) for v in obj]
    return obj


def export() -> int:
    deny = [l.strip() for l in DENYLIST.read_text().splitlines() if l.strip()] if DENYLIST.exists() else []
    if not deny:
        print("WARNING: .sensitive-denylist missing/empty - only structural redaction is applied")
    if DST.exists():
        shutil.rmtree(DST)
    problems = []
    for run_dir in sorted(d for d in SRC.iterdir() if (d / "results.jsonl").is_file()):
        before = {f: sha(run_dir / f) for f in FILES if (run_dir / f).exists()}
        mapping = build_mapping(run_dir)
        out = DST / run_dir.name
        out.mkdir(parents=True)
        for f in FILES:
            src = run_dir / f
            if not src.exists():
                continue
            if f.endswith(".jsonl"):
                orig = [json.loads(l) for l in src.read_text().splitlines() if l.strip()]
                red = [redact_obj(r, mapping, deny) for r in orig]
                (out / f).write_text("".join(json.dumps(r) + "\n" for r in red))
                if [strip_identifiers(r) for r in orig] != [strip_identifiers(r) for r in red]:
                    problems.append(f"{run_dir.name}/{f}: non-identifier content changed")
            elif f.endswith(".json"):
                orig = json.loads(src.read_text())
                red = redact_obj(orig, mapping, deny)
                (out / f).write_text(json.dumps(red, indent=2) + "\n")
                if strip_identifiers(orig) != strip_identifiers(red):
                    problems.append(f"{run_dir.name}/{f}: non-identifier content changed")
            else:
                text = src.read_text()
                red = redact_text(text, mapping, deny)
                (out / f).write_text(red)
                if text != red and not any(k in text for k in mapping):
                    problems.append(f"{run_dir.name}/{f}: unexpected text change")
        # no denylisted or mapped real value may survive
        blob = "".join(p.read_text() for p in out.iterdir())
        leaked = [v for v in set(deny) | set(mapping) if v in blob]
        if leaked:
            problems.append(f"{run_dir.name}: {len(leaked)} sensitive value(s) remain")
        if before != {f: sha(run_dir / f) for f in before}:
            problems.append(f"{run_dir.name}: ORIGINAL FILES CHANGED")
        (out / "PUBLIC_COPY.md").write_text(
            f"# Sanitized copy of run `{run_dir.name}`\n\n"
            "Derived from the private original by `scripts/docs/export_public_results.py`.\n"
            "Only identifiers were changed: AWS account ID -> `111122223333`, Knowledge Base IDs -> "
            "`KBFIXED001` / `KBHIER0001`, request IDs -> null. All answers, sources, scores, metrics, latencies, "
            "token counts and costs are identical to the original (verified by the export script and tests).\n\n"
            "`rescored_v2_metadata.json` lists SHA-256 hashes of the *private originals*, so they differ from "
            "the hashes of these sanitized files.\n")
        print(f"exported {run_dir.name}: {len(list(out.iterdir()))} files, identifiers mapped: "
              f"{sorted(set(mapping.values()))}")
    if problems:
        print("EXPORT FAILED:\n  " + "\n  ".join(problems))
        return 1
    print("verification: non-identifier content identical; no sensitive values remain; originals unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(export())
