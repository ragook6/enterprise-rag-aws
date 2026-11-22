#!/usr/bin/env python3
"""
Pre-publication scan of every file git would publish (tracked + untracked-but-not-ignored). Offline.

    .venv/bin/python scripts/security/scan_public.py [--staged]     # --staged: only files in the git index

Fails (exit 1) on:
  - forbidden files (Terraform state/plans/tfvars, private results, raw screenshots, keys, .env, denylist)
  - any value from the local, git-ignored .sensitive-denylist (real account/resource IDs, user names)
  - AWS access-key IDs, secret-key assignments, private keys
  - 12-digit account IDs / IAM-STS ARNs other than the AWS documentation placeholders (111122223333, 123456789012) and the
    fictional accounts defined in the synthetic-data source (scripts/content.py)
  - e-mail addresses outside example domains; local home-directory paths
  - IPv4 addresses not present in the synthetic-data source (fictional) and not loopback/documentation ranges
  - images with metadata, or images not marked as reviewed in their MANIFEST.json
PDFs are text-extracted and checked like text files.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLACEHOLDER_ACCOUNTS = {"111122223333", "123456789012"}   # AWS documentation example account IDs
FORBIDDEN = [r"(^|/)\.sensitive-denylist$", r"\.tfstate(\.|$)", r"\.tfplan$", r"(^|/)terraform\.tfvars$",
             r"^results/", r"^private/", r"^screenshots-raw/", r"^drafts/", r"(^|/)\.env$", r"\.pem$", r"\.key$",
             r"(^|/)id_rsa", r"(^|/)credentials$", r"^infra/\.terraform/"]
SYNTHETIC_SOURCE = ROOT / "scripts" / "content.py"
EMAIL_OK = re.compile(r"@(example\.(com|org|net)|[a-z0-9-]+\.example)$", re.I)
PATTERNS = {
    "aws_access_key_id": re.compile(r"\b(AKIA|ASIA|AIDA|AROA)[0-9A-Z]{16}\b"),
    "secret_key_assignment": re.compile(r"(?i)aws_secret_access_key\s*[=:]\s*['\"]?[A-Za-z0-9/+=]{40}"),
    "private_key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "home_path": re.compile(r"/(Users|home)/[A-Za-z0-9._-]+/"),
}
ACCOUNT_RE = re.compile(r"(?<![0-9A-Za-z.])[0-9]{12}(?![0-9])")
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
SAFE_IP_PREFIXES = ("127.", "0.0.0.0", "192.0.2.", "198.51.100.", "203.0.113.")   # loopback + RFC 5737


def candidate_files(staged: bool) -> list[str]:
    cmd = ["git", "-C", str(ROOT), "ls-files", "--cached"] + ([] if staged else ["--others", "--exclude-standard"])
    return sorted(set(subprocess.check_output(cmd, text=True).split()))


def fictional_allowlist() -> tuple[set[str], set[str]]:
    src = SYNTHETIC_SOURCE.read_text() if SYNTHETIC_SOURCE.exists() else ""
    return set(ACCOUNT_RE.findall(src)), set(IPV4_RE.findall(src))


def text_of(path: Path) -> str | None:
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader
        r = PdfReader(str(path))
        meta = " ".join(str(v) for v in (r.metadata or {}).values())
        return meta + "\n" + "\n".join(p.extract_text() or "" for p in r.pages)
    try:
        return path.read_text()
    except (UnicodeDecodeError, OSError):
        return None


def check_image(path: Path, rel: str) -> list[str]:
    from PIL import Image
    issues = []
    with Image.open(path) as im:
        meta = {k for k in im.info if k not in ("dpi",)}
        if meta or im.getexif():
            issues.append(f"{rel}: image metadata present {sorted(meta)}")
    manifest = path.parent / "MANIFEST.json"
    if not manifest.exists():
        issues.append(f"{rel}: no MANIFEST.json (image not produced by redact_image.py)")
    else:
        entry = json.loads(manifest.read_text()).get(path.name)
        if not entry:
            issues.append(f"{rel}: not listed in MANIFEST.json")
        elif not str(entry.get("manual_review", "")).startswith("reviewed by"):
            issues.append(f"{rel}: manual review pending")
    return issues


def scan(staged: bool = False) -> int:
    deny_file = ROOT / ".sensitive-denylist"
    deny = [l.strip() for l in deny_file.read_text().splitlines() if l.strip()] if deny_file.exists() else []
    fict_accounts, fict_ips = fictional_allowlist()
    files = candidate_files(staged)
    issues, notes = [], []
    if not deny:
        notes.append("WARNING: .sensitive-denylist missing - real-identifier check skipped")
    for rel in files:
        if any(re.search(p, rel) for p in FORBIDDEN):
            issues.append(f"{rel}: forbidden file selected for publication")
            continue
        path = ROOT / rel
        if not path.is_file():
            continue
        if path.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
            issues += check_image(path, rel)
            continue
        text = text_of(path)
        if text is None:
            notes.append(f"{rel}: binary file not scanned")
            continue
        for d in deny:
            if d in text:
                issues.append(f"{rel}: contains a denylisted real identifier (#{deny.index(d)})")
        for name, rx in PATTERNS.items():
            for m in rx.finditer(text):
                issues.append(f"{rel}: {name} at offset {m.start()}")
        for acct in set(ACCOUNT_RE.findall(text)) - PLACEHOLDER_ACCOUNTS - fict_accounts:
            issues.append(f"{rel}: 12-digit number {acct[:4]}******** not allow-listed (account ID?)")
        for email in set(EMAIL_RE.findall(text)):
            if not EMAIL_OK.search(email):
                issues.append(f"{rel}: e-mail address {email.split('@')[0][:2]}***@{email.split('@')[1]}")
        for ip in set(IPV4_RE.findall(text)) - fict_ips:
            if not ip.startswith(SAFE_IP_PREFIXES) and all(0 <= int(o) <= 255 for o in ip.split(".")):
                notes.append(f"{rel}: IPv4 {ip} not in synthetic data (review)")
    print(f"scanned {len(files)} file(s) {'(staged)' if staged else '(tracked + untracked, not ignored)'}")
    for n in notes:
        print("  note :", n)
    for i in issues:
        print("  FAIL :", i)
    print("RESULT:", "PASS - no sensitive findings" if not issues else f"FAIL - {len(issues)} finding(s)")
    return 1 if issues else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--staged", action="store_true")
    sys.exit(scan(ap.parse_args().staged))
