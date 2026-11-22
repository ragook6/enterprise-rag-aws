#!/usr/bin/env python3
"""
READ-ONLY completeness check: does each S3 Vectors index contain every source PDF?

    AWS_PROFILE=hrl-mfa .venv/bin/python scripts/check_index_coverage.py [--arms ...] [--min-coverage 0.97]

Word coverage = share of a PDF's words that appear in the union of that document's chunk
texts (AMAZON_BEDROCK_TEXT). Ingestion-job statistics can report 0 failures while chunks
are missing, so this check is the source of truth before any evaluation.
"""
import argparse, collections, glob, json, os, re, subprocess, sys
from pathlib import Path
import boto3
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
ap = argparse.ArgumentParser()
ap.add_argument("--profile", default="hrl-mfa")
ap.add_argument("--region", default="us-west-2")
ap.add_argument("--arms", nargs="+")
ap.add_argument("--min-coverage", type=float, default=0.97)
args = ap.parse_args()

norm = lambda t: re.sub(r"\s+", " ", t).strip()
out = json.loads(subprocess.check_output(["terraform", f"-chdir={ROOT/'infra'}", "output", "-json"]))
vb = out["vector_bucket"]["value"]
exps = {k: v for k, v in out["experiments"]["value"].items() if not args.arms or k in args.arms}
pdf = {os.path.basename(f): norm(" ".join(p.extract_text() for p in PdfReader(f).pages))
       for f in glob.glob(str(ROOT / "data/documents/*.pdf"))}
sv = boto3.Session(profile_name=args.profile, region_name=args.region).client("s3vectors")

all_ok = True
for arm, e in exps.items():
    idx = e["vector_index_arn"].split("/index/")[-1]
    vecs, tok = [], None
    while True:
        kw = dict(vectorBucketName=vb, indexName=idx, maxResults=500, returnMetadata=True)
        if tok: kw["nextToken"] = tok
        r = sv.list_vectors(**kw); vecs += r.get("vectors", []); tok = r.get("nextToken")
        if not tok: break
    per = collections.defaultdict(list)
    for v in vecs:
        m = re.search(r"documents/([^'\"]+\.pdf)", v["metadata"]["AMAZON_BEDROCK_METADATA"])
        per[m.group(1) if m else "?"].append(norm(v["metadata"]["AMAZON_BEDROCK_TEXT"]))
    print(f"\n[{arm}] {len(vecs)} vectors in {idx}")
    print(f"   {'document':36s} {'vectors':>7} {'pdf words':>9} {'coverage':>9}")
    for doc in sorted(pdf):
        words = pdf[doc].split(); vocab = set(" ".join(per.get(doc, [])).split())
        cov = sum(w in vocab for w in words) / len(words)
        ok = cov >= args.min_coverage and per.get(doc); all_ok &= bool(ok)
        print(f"   {doc:36s} {len(per.get(doc, [])):7d} {len(words):9d} {cov:8.1%}  {'OK' if ok else 'BELOW THRESHOLD'}")
    extra = set(per) - set(pdf)
    if extra: print("   unexpected sources:", extra); all_ok = False
print(f"\nRESULT: {'all documents >= ' + format(args.min_coverage, '.0%') + ' coverage' if all_ok else 'COVERAGE GAPS'}")
sys.exit(0 if all_ok else 1)
