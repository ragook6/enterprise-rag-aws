#!/usr/bin/env python3
"""
Offline documentation checks for every Markdown file that would be published.

    .venv/bin/python scripts/docs/check_docs.py

- image and relative file links resolve; in-document anchors exist (GitHub heading slugs)
- code fences are balanced
- every `scripts/<name>.py` mentioned exists, and every `--flag` used with it on the same line is defined in that
  script's source (argparse), so README commands match the code
- generated results blocks are up to date (scripts/docs/generate_results_doc.py --check)
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
SCRIPT_CMD = re.compile(r"scripts/([\w/]+\.py)([^\n`|]*)")
FLAG = re.compile(r"(?<![\w-])(--[a-z][a-z0-9-]*)")


def slug(heading: str) -> str:
    s = re.sub(r"[`*_]|<[^>]+>", "", heading.strip().lower())
    s = re.sub(r"[^\w\- ]", "", s)
    return s.replace(" ", "-")


def md_files() -> list[Path]:
    out = subprocess.check_output(["git", "-C", str(ROOT), "ls-files", "--cached", "--others", "--exclude-standard",
                                   "*.md"], text=True).split()
    return [ROOT / f for f in sorted(set(out))]


def main() -> int:
    problems = []
    for md in md_files():
        rel, text = md.relative_to(ROOT), md.read_text()
        if text.count("```") % 2:
            problems.append(f"{rel}: unbalanced code fences")
        body = re.sub(r"```.*?```", "", text, flags=re.S)          # ignore code blocks for links/anchors
        anchors = {slug(h) for h in re.findall(r"^#{1,6}\s+(.+)$", body, re.M)}
        for target in LINK.findall(body):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            if target.startswith("#"):
                if target[1:] not in anchors:
                    problems.append(f"{rel}: anchor {target} not found")
                continue
            path = (md.parent / target.split("#")[0]).resolve()
            if not path.exists():
                problems.append(f"{rel}: link target {target} does not exist")
        for name, rest in SCRIPT_CMD.findall(text):
            script = ROOT / "scripts" / name
            if not script.exists():
                problems.append(f"{rel}: scripts/{name} does not exist")
                continue
            src = script.read_text()
            for flag in FLAG.findall(rest.split("#")[0]):
                if f'"{flag}"' not in src and f"'{flag}'" not in src:
                    problems.append(f"{rel}: scripts/{name} has no option {flag}")
    gen = subprocess.run([sys.executable, str(ROOT / "scripts/docs/generate_results_doc.py"), "--check"],
                         capture_output=True, text=True)
    if gen.returncode != 0:
        problems.append("generated results docs out of date: " + gen.stdout.strip())
    print(f"checked {len(md_files())} Markdown file(s)")
    for p in problems:
        print("  FAIL:", p)
    print("RESULT:", "PASS" if not problems else f"FAIL - {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
