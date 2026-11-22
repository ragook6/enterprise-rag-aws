#!/usr/bin/env python3
"""
Gate 3 (Option B): ONE minimal Claude Haiku 5.5 call via Amazon Bedrock Runtime
(Anthropic SDK AnthropicBedrock client, SigV4) as the least-privilege runner role.

    AWS_PROFILE=hrl-mfa .venv/bin/python scripts/gate3_runtime_test.py

The role is assumed with a SESSION POLICY limited to the two bedrock:InvokeModel
statements (inference profile + underlying model via that profile). Effective
permissions = role policy INTERSECT session policy, so success proves those two
statements are sufficient. No retries (max_retries=0); a denial invokes no model.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import anthropic
import boto3
from anthropic import AnthropicBedrock

ROOT = Path(__file__).resolve().parent.parent
PROFILE, REGION = "hrl-mfa", "us-west-2"
MODEL = "us.anthropic.claude-haiku-5-5"            # approved inference profile (Option B)
PRICE_IN, PRICE_OUT = 0.11e-6, 0.55e-6             # USD/token, us. profile, Price List 2026-11-01
KEEP = ("ProvisionalInvokeConfiguredProfile", "ProvisionalInvokeUnderlyingModelViaProfileOnly")

for var in ("AWS_BEARER_TOKEN_BEDROCK", "ANTHROPIC_AWS_API_KEY", "ANTHROPIC_API_KEY"):
    if os.environ.get(var):
        sys.exit(f"Refusing to run: {var} is set; this test must use AWS SigV4 only.")

out = json.loads(subprocess.check_output(["terraform", f"-chdir={ROOT / 'infra'}", "output", "-json"]))
role_arn, policy_arn = out["runner_role_arn"]["value"], out["runner_policy_arn"]["value"]

src = boto3.Session(profile_name=PROFILE, region_name=REGION)
iam = src.client("iam")
ver = iam.get_policy(PolicyArn=policy_arn)["Policy"]["DefaultVersionId"]
stmts = iam.get_policy_version(PolicyArn=policy_arn, VersionId=ver)["PolicyVersion"]["Document"]["Statement"]
session_policy = {"Version": "2012-10-17", "Statement": [s for s in stmts if s["Sid"] in KEEP]}
assert len(session_policy["Statement"]) == 2, "expected exactly the two InvokeModel statements"
print("Session policy allows only:")
for s in session_policy["Statement"]:
    print(f"   {s['Sid']}: {s['Action']} on {s['Resource']}" + (f" if {s['Condition']}" if "Condition" in s else ""))

c = src.client("sts").assume_role(RoleArn=role_arn, RoleSessionName="gate3-runtime-test",
                                  DurationSeconds=900, Policy=json.dumps(session_policy))["Credentials"]
print("Assumed:", role_arn.split("/")[-1], f"(temporary key {c['AccessKeyId'][:4]}...{c['AccessKeyId'][-4:]})")

client = AnthropicBedrock(
    aws_region=REGION,
    aws_access_key=c["AccessKeyId"], aws_secret_key=c["SecretAccessKey"], aws_session_token=c["SessionToken"],
    max_retries=0,                                   # one attempt only
)
print(f"Endpoint: {client.base_url}  model: {MODEL}  auth: SigV4 (service 'bedrock')\n")

t0 = time.perf_counter()
try:
    msg = client.messages.create(
        model=MODEL,
        max_tokens=256,
        messages=[{"role": "user", "content": "Connectivity test. Reply with exactly: OK"}],
    )
except anthropic.APIStatusError as e:
    print(f"FAILED after {time.perf_counter() - t0:.2f}s: {type(e).__name__} (HTTP {e.status_code})")
    print("   ", e.message[:800])
    sys.exit(1)
except anthropic.APIConnectionError as e:
    print(f"FAILED: connection error: {e}")
    sys.exit(1)
latency = time.perf_counter() - t0

if msg.stop_reason == "refusal":
    print("Model returned a refusal:", getattr(msg, "stop_details", None))
    sys.exit(1)
text = "".join(b.text for b in msg.content if b.type == "text").strip()
u = msg.usage
cost = u.input_tokens * PRICE_IN + u.output_tokens * PRICE_OUT
print(f"Response      : {text!r}")
print(f"Content blocks: {[b.type for b in msg.content]}   stop_reason: {msg.stop_reason}")
print(f"Model         : {msg.model}")
print(f"Latency       : {latency:.2f} s (end-to-end, non-streaming)")
print(f"Tokens        : input={u.input_tokens}  output={u.output_tokens}")
print(f"Est. cost     : USD {cost:.7f}")
print(f"Request ID    : {msg._request_id}")
