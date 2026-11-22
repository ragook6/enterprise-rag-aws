#!/usr/bin/env python3
"""
Accept the REVIEWED AWS Marketplace offer for Claude Haiku 5.5 - exactly once.

    AWS_PROFILE=hrl-mfa .venv/bin/python scripts/accept_model_agreement.py \
        --reviewed-offer private/reviewed_offer.json --expected-account <ACCOUNT_ID> --expected-user <IAM_USER>

1. Re-reads the live offer and compares it with the values reviewed and approved on
   --reviewed-offer file (offer ID, full rate card, legal document, support term, term types).
   ANY difference -> abort before making changes.
2. Calls bedrock:CreateFoundationModelAgreement ONE time (SDK retries disabled).
3. Polls GetFoundationModelAvailability (read-only) until agreement is AVAILABLE.
"""
import sys
import time

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

import argparse
import json

ap = argparse.ArgumentParser(description="Accept a reviewed Bedrock Marketplace model offer exactly once.")
ap.add_argument("--reviewed-offer", required=True, help="JSON of the offer you reviewed (see scripts/reviewed_offer.example.json)")
ap.add_argument("--expected-account", required=True, help="12-digit AWS account ID the agreement must apply to")
ap.add_argument("--expected-user", required=True, help="IAM user name of the MFA admin session")
ap.add_argument("--profile", default="hrl-mfa")
ap.add_argument("--region", default="us-west-2")
args = ap.parse_args()
rev = json.load(open(args.reviewed_offer))
PROFILE, REGION, MODEL_ID = args.profile, args.region, rev["model_id"]
REVIEWED_OFFER_ID, REVIEWED_LEGAL_DOC = rev["offer_id"], rev["legal_doc"]
REVIEWED_SUPPORT, REVIEWED_TERM_TYPES, REVIEWED_RATES = rev["support"], set(rev["term_types"]), rev["rates_usd_per_1m"]

sess = boto3.Session(profile_name=PROFILE, region_name=REGION)
ident = sess.client("sts").get_caller_identity()
print("Caller:", ident["Arn"], "| account", ident["Account"], "| region", REGION)
if not ident["Arn"].endswith(f":user/{args.expected_user}") or ident["Account"] != args.expected_account:
    sys.exit("ABORT: unexpected identity")
b = sess.client("bedrock", config=Config(retries={"total_max_attempts": 1, "mode": "standard"}))

# ---- 1. Re-verify the live offer against the reviewed one ---------------------------
offers = b.list_foundation_model_agreement_offers(modelId=MODEL_ID)["offers"]
problems = []
if len(offers) != 1:
    problems.append(f"expected 1 offer, found {len(offers)}")
o = offers[0]
td = o.get("termDetails", {})
live_rates = {r["dimension"]: r["price"] for r in td.get("usageBasedPricingTerm", {}).get("rateCard", [])}
checks = {
    "offer ID": (o.get("offerId"), REVIEWED_OFFER_ID),
    "term types": (set(k for k, v in td.items() if v), REVIEWED_TERM_TYPES),
    "rate card (20 dimensions)": (live_rates, REVIEWED_RATES),
    "support term": (td.get("supportTerm"), REVIEWED_SUPPORT),
    "legal document": (REVIEWED_LEGAL_DOC in td.get("legalTerm", {}).get("url", ""), True),
}
for name, (live, reviewed) in checks.items():
    same = live == reviewed
    print(f"{'MATCH ' if same else 'DIFF  '} {name}")
    if not same:
        problems.append(f"{name}: live={live!r} reviewed={reviewed!r}")
if problems:
    print("\nABORT - offer differs from the reviewed offer; no agreement created:")
    for p in problems:
        print("  -", p)
    sys.exit(2)

before = b.get_foundation_model_availability(modelId=MODEL_ID)["agreementAvailability"]["status"]
print(f"Agreement status before: {before}")
if before == "AVAILABLE":
    print("Agreement already AVAILABLE - nothing to accept.")
    sys.exit(0)

# ---- 2. Exactly one CreateFoundationModelAgreement call ------------------------------
print(f"\nCalling CreateFoundationModelAgreement(modelId={MODEL_ID}, offer {o['offerId']}) - single attempt")
try:
    r = b.create_foundation_model_agreement(modelId=MODEL_ID, offerToken=o["offerToken"])
    print("Accepted. Response modelId:", r.get("modelId"),
          "| HTTP", r["ResponseMetadata"]["HTTPStatusCode"], "| RequestId", r["ResponseMetadata"]["RequestId"])
except ClientError as e:
    err = e.response["Error"]
    print(f"FAILED: {err['Code']}: {err['Message']}  (RequestId {e.response['ResponseMetadata'].get('RequestId')})")
    sys.exit(1)

# ---- 3. Poll (read-only) until AVAILABLE ---------------------------------------------
deadline = time.time() + 15 * 60
status = None
while time.time() < deadline:
    a = b.get_foundation_model_availability(modelId=MODEL_ID)
    status = a["agreementAvailability"]["status"]
    msg = a["agreementAvailability"].get("errorMessage")
    print(f"  {time.strftime('%H:%M:%S', time.gmtime())}Z agreement={status}"
          f" authorization={a['authorizationStatus']} entitlement={a['entitlementAvailability']}"
          + (f" error={msg}" if msg else ""))
    if status in ("AVAILABLE", "ERROR"):
        break
    time.sleep(20)
print("\nRESULT: agreement", status)
sys.exit(0 if status == "AVAILABLE" else 1)
