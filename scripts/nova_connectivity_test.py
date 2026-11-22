#!/usr/bin/env python3
"""
Nova Micro step 2: exactly ONE minimal inference call via the Amazon Bedrock Converse API
as the MFA-gated least-privilege runner role.

    AWS_PROFILE=hrl-mfa .venv/bin/python scripts/nova_connectivity_test.py

Model us.amazon.nova-micro-v1:0, us-west-2, temperature 0, maxTokens 100, SDK retries disabled.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parent.parent
PROFILE, REGION = "hrl-mfa", "us-west-2"
MODEL_ID = "us.amazon.nova-micro-v1:0"
QUESTION = "What is Amazon Bedrock?"
PRICE_IN, PRICE_OUT = 0.035e-6, 0.14e-6   # USD/token, on-demand, Price List us-west-2

# 1. MFA session must be valid (read-only guard script)
rc = subprocess.run([sys.executable, str(ROOT / "scripts/check_mfa_session.py"), "--profile", PROFILE, "--min-minutes", "5"],
                    capture_output=True, text=True)
print("MFA session:", [l for l in rc.stdout.splitlines() if "valid for" in l or "RESULT" in l])
if rc.returncode != 0:
    sys.exit("STOP: MFA session check failed\n" + rc.stdout)

# 2. Assume the runner role (its trust policy requires MFA) and verify the credentials
role_arn = json.loads(subprocess.check_output(["terraform", f"-chdir={ROOT / 'infra'}", "output", "-json", "runner_role_arn"]))
src = boto3.Session(profile_name=PROFILE, region_name=REGION)
c = src.client("sts").assume_role(RoleArn=role_arn, RoleSessionName="nova-connectivity-test", DurationSeconds=900)["Credentials"]
runner = boto3.Session(aws_access_key_id=c["AccessKeyId"], aws_secret_access_key=c["SecretAccessKey"],
                       aws_session_token=c["SessionToken"], region_name=REGION)
ident = runner.client("sts").get_caller_identity()["Arn"]
print("Assumed role:", ident, f"| key {c['AccessKeyId'][:4]}...{c['AccessKeyId'][-4:]} | expires {c['Expiration']:%H:%M:%S} UTC")
if ":assumed-role/hrl-rag-experiment-runner/" not in ident:
    sys.exit("STOP: not running as the runner role")

# 3. Exactly one Converse call (retries disabled)
rt = runner.client("bedrock-runtime", config=Config(retries={"total_max_attempts": 1, "mode": "standard"}))
print(f"\nConverse -> {rt.meta.endpoint_url}  model={MODEL_ID}  temperature=0  maxTokens=100")
print(f"Question: {QUESTION!r}")
t0 = time.perf_counter()
try:
    r = rt.converse(
        modelId=MODEL_ID,
        messages=[{"role": "user", "content": [{"text": QUESTION}]}],
        inferenceConfig={"temperature": 0, "maxTokens": 100},
    )
except ClientError as e:
    err = e.response["Error"]
    print(f"\nFAILED after {time.perf_counter() - t0:.2f}s: {err['Code']}: {err['Message']}")
    print("RequestId:", e.response.get("ResponseMetadata", {}).get("RequestId"))
    sys.exit(1)
wall = time.perf_counter() - t0

text = "".join(b.get("text", "") for b in r["output"]["message"]["content"])
u = r["usage"]
cost = u["inputTokens"] * PRICE_IN + u["outputTokens"] * PRICE_OUT
print("\nSUCCESS")
print(f"Response      :\n{text}\n")
print(f"stopReason    : {r['stopReason']}")
print(f"Tokens        : input={u['inputTokens']}  output={u['outputTokens']}  total={u['totalTokens']}")
print(f"Latency       : service {r['metrics']['latencyMs']} ms | end-to-end {wall * 1000:.0f} ms")
print(f"Est. cost     : USD {cost:.8f}")
print(f"RequestId     : {r['ResponseMetadata']['RequestId']}")
