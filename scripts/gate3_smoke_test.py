#!/usr/bin/env python3
"""
Gate 3 smoke test: ONE Claude Haiku 5.5 call through Amazon Bedrock (Anthropic SDK,
AnthropicBedrockMantle, SigV4) as the least-privilege runner role, plus one Retrieve.

    AWS_PROFILE=hrl-mfa .venv/bin/python scripts/gate3_smoke_test.py

To learn which "Provisional*" statements of the runner policy are really needed WITHOUT
changing IAM, the role is assumed with a SESSION POLICY that omits them. Effective
permissions = role policy INTERSECT session policy, so a success proves the provisional
statements are unnecessary for that call. A denial changes nothing and invokes no model.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import anthropic
import boto3
from anthropic import AnthropicBedrockMantle
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parent.parent
ap = argparse.ArgumentParser()
ap.add_argument("--profile", default="hrl-mfa")
ap.add_argument("--region", default="us-west-2")
ap.add_argument("--full-role", action="store_true",
                help="no session policy (use only if the restricted test was denied)")
args = ap.parse_args()

for var in ("AWS_BEARER_TOKEN_BEDROCK", "ANTHROPIC_AWS_API_KEY", "ANTHROPIC_API_KEY"):
    if os.environ.get(var):
        sys.exit(f"Refusing to run: {var} is set; this test must use SigV4 only.")

cfg = json.loads((ROOT / "experiments/experiment_config.json").read_text())["controlled_variables"]["generation"]
model_id = cfg["inference_profile_id"]
out = json.loads(subprocess.check_output(["terraform", f"-chdir={ROOT / 'infra'}", "output", "-json"]))
runner_arn = out["runner_role_arn"]["value"]
policy_arn = out["runner_policy_arn"]["value"]
kb_id = out["experiments"]["value"]["baseline-fixed100"]["knowledge_base_id"]

src = boto3.Session(profile_name=args.profile, region_name=args.region)
iam = src.client("iam")
ver = iam.get_policy(PolicyArn=policy_arn)["Policy"]["DefaultVersionId"]
doc = iam.get_policy_version(PolicyArn=policy_arn, VersionId=ver)["PolicyVersion"]["Document"]
kept = [s for s in doc["Statement"] if not s["Sid"].startswith("Provisional")]
dropped = [s["Sid"] for s in doc["Statement"] if s["Sid"].startswith("Provisional")]

assume = dict(RoleArn=runner_arn, RoleSessionName="gate3-smoke-test", DurationSeconds=900)
if not args.full_role:
    session_policy = {"Version": "2012-10-17",
                      "Statement": [s for s in kept if s["Sid"] in
                                    ("RetrieveFromExperimentKBsOnly", "MantleInferenceConfiguredModelOnly")]}
    assume["Policy"] = json.dumps(session_policy, separators=(",", ":"))
    print("Session policy statements:", [s["Sid"] for s in session_policy["Statement"]])
    print("Excluded (provisional):   ", dropped)
creds = src.client("sts").assume_role(**assume)["Credentials"]
print("Assumed:", runner_arn.split("/")[-1], "| full role" if args.full_role else "| restricted by session policy")

results = {}

# --- 1. Retrieve (Titan embeds the query inside Bedrock) --------------------------
rt = boto3.Session(aws_access_key_id=creds["AccessKeyId"], aws_secret_access_key=creds["SecretAccessKey"],
                   aws_session_token=creds["SessionToken"], region_name=args.region)
try:
    r = rt.client("bedrock-agent-runtime").retrieve(
        knowledgeBaseId=kb_id, retrievalQuery={"text": "What is the SQS visibility timeout for the order events queue?"},
        retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": 1, "overrideSearchType": "SEMANTIC"}})
    top = r["retrievalResults"][0]
    results["retrieve"] = "OK"
    print(f"\nRetrieve: OK  top score={top['score']:.3f}  \"{' '.join(top['content']['text'].split())[:80]}...\"")
except ClientError as e:
    results["retrieve"] = e.response["Error"]["Code"]
    print(f"\nRetrieve: {e.response['Error']['Code']}: {e.response['Error']['Message'][:300]}")

# --- 2. ONE Claude Haiku 5.5 call via Anthropic SDK -> bedrock-mantle (SigV4) -----
client = AnthropicBedrockMantle(
    aws_region=args.region,
    aws_access_key=creds["AccessKeyId"], aws_secret_key=creds["SecretAccessKey"],
    aws_session_token=creds["SessionToken"],   # explicit keys => SigV4, never API-key mode
    max_retries=0)
print(f"\nClaude call: model={model_id} endpoint={client.base_url} effort={cfg['effort']}")
try:
    msg = client.messages.create(
        model=model_id,
        max_tokens=512,
        output_config={"effort": "low"},
        messages=[{"role": "user", "content": "Connectivity test. Reply with exactly: OK"}],
    )
    if msg.stop_reason == "refusal":
        results["claude"] = "refusal"
        print("Claude: refused", getattr(msg, "stop_details", None))
    else:
        text = "".join(b.text for b in msg.content if b.type == "text").strip()
        u = msg.usage
        cost = u.input_tokens * 0.11e-6 + u.output_tokens * 0.55e-6
        results["claude"] = "OK"
        print(f"Claude: OK  reply={text!r}  stop_reason={msg.stop_reason}  model={msg.model}")
        print(f"        usage in={u.input_tokens} out={u.output_tokens}  est. cost USD {cost:.6f}  request_id={msg._request_id}")
except anthropic.PermissionDeniedError as e:
    results["claude"] = "PermissionDenied"
    print(f"Claude: PermissionDenied (403): {e.message[:500]}")
except anthropic.APIStatusError as e:
    results["claude"] = f"HTTP {e.status_code}"
    print(f"Claude: {type(e).__name__} ({e.status_code}): {e.message[:500]}")
except anthropic.APIConnectionError as e:
    results["claude"] = "connection error"
    print(f"Claude: connection error: {e}")

print("\nRESULTS:", results)
sys.exit(0 if all(v == "OK" for v in results.values()) else 1)
