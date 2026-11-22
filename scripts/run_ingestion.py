#!/usr/bin/env python3
"""
Gate 2: start one ingestion job per Knowledge Base AS THE LEAST-PRIVILEGE RUNNER ROLE,
then poll until both finish and print the statistics.

    AWS_PROFILE=hrl-mfa .venv/bin/python scripts/run_ingestion.py

- Source credentials: the MFA session profile (default hrl-mfa). The runner role's trust
  policy requires aws:MultiFactorAuthPresent=true, which that session satisfies.
- Only bedrock:StartIngestionJob / GetIngestionJob are called. No model is invoked by
  this script; Bedrock itself calls Titan Embeddings V2 inside the ingestion job.
- Idempotent: a clientToken per data source prevents duplicate jobs on retry.
"""
import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parent.parent
ap = argparse.ArgumentParser()
ap.add_argument("--profile", default="hrl-mfa")
ap.add_argument("--region", default="us-west-2")
ap.add_argument("--timeout-min", type=int, default=20)
ap.add_argument("--token-suffix", default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"),
                help="idempotency suffix; reusing one returns the earlier job instead of starting a new one")
ap.add_argument("--arms", nargs="+", help="experiment keys to ingest (default: all)")
args = ap.parse_args()

out = json.loads(subprocess.check_output(["terraform", f"-chdir={ROOT / 'infra'}", "output", "-json"]))
experiments = out["experiments"]["value"]
if args.arms:
    unknown = set(args.arms) - set(experiments)
    if unknown:
        sys.exit(f"unknown arms: {sorted(unknown)}; valid: {sorted(experiments)}")
    experiments = {k: v for k, v in experiments.items() if k in args.arms}
print("Arms to ingest:", sorted(experiments))
runner_arn = out["runner_role_arn"]["value"]

src = boto3.Session(profile_name=args.profile, region_name=args.region)
creds = src.client("sts").assume_role(
    RoleArn=runner_arn, RoleSessionName="gate2-ingestion", DurationSeconds=3600)["Credentials"]
runner = boto3.Session(aws_access_key_id=creds["AccessKeyId"], aws_secret_access_key=creds["SecretAccessKey"],
                       aws_session_token=creds["SessionToken"], region_name=args.region)
print("Running as:", runner.client("sts").get_caller_identity()["Arn"])
ba = runner.client("bedrock-agent")

jobs = {}
for arm, e in experiments.items():
    r = ba.start_ingestion_job(
        knowledgeBaseId=e["knowledge_base_id"], dataSourceId=e["data_source_id"],
        clientToken=hashlib.sha256(f"gate2-{arm}-{args.token_suffix}".encode()).hexdigest(),  # 64 chars (API: 33-256)
        description=f"Gate 2 initial ingestion ({arm})")["ingestionJob"]
    jobs[arm] = r["ingestionJobId"]
    print(f"Started  {arm:22s} KB={e['knowledge_base_id']} DS={e['data_source_id']} job={r['ingestionJobId']} status={r['status']}")

deadline = time.time() + args.timeout_min * 60
final = {}
while len(final) < len(jobs) and time.time() < deadline:
    time.sleep(10)
    for arm, job_id in jobs.items():
        if arm in final:
            continue
        e = experiments[arm]
        j = ba.get_ingestion_job(knowledgeBaseId=e["knowledge_base_id"], dataSourceId=e["data_source_id"],
                                 ingestionJobId=job_id)["ingestionJob"]
        if j["status"] in ("COMPLETE", "FAILED", "STOPPED"):
            final[arm] = j
            print(f"Finished {arm:22s} status={j['status']}")

ok = len(final) == len(jobs)
for arm, j in final.items():
    st = j.get("statistics", {})
    dur = (j["updatedAt"] - j["startedAt"]).total_seconds()
    print(f"\n[{arm}] job {j['ingestionJobId']}  status={j['status']}  duration={dur:.0f}s")
    for k in ("numberOfDocumentsScanned", "numberOfNewDocumentsIndexed", "numberOfModifiedDocumentsIndexed",
              "numberOfDocumentsDeleted", "numberOfDocumentsFailed", "numberOfMetadataDocumentsScanned"):
        print(f"   {k:34s} {st.get(k, 0)}")
    for reason in j.get("failureReasons", []):
        print("   FAILURE:", reason[:400])
    ok &= j["status"] == "COMPLETE" and st.get("numberOfDocumentsFailed", 0) == 0
if len(final) < len(jobs):
    print("\nTIMEOUT: still running:", [a for a in jobs if a not in final])
print("\nRESULT:", "INGESTION COMPLETE" if ok else "INGESTION NOT CLEAN - see above")
sys.exit(0 if ok else 1)
