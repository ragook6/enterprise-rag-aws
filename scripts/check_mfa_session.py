#!/usr/bin/env python3
"""
READ-ONLY guard: prove that tools will use the temporary MFA session, not long-lived keys.

    .venv/bin/python scripts/check_mfa_session.py [--profile hrl-mfa] [--min-minutes 15]

Exits non-zero if any check fails. Prints masked key IDs only.

Why this also covers Terraform: the Terraform AWS provider resolves credentials in this
order: (1) provider-block arguments, (2) environment variables (AWS_ACCESS_KEY_ID ...),
(3) the shared credentials/config files for the profile named by AWS_PROFILE, ...
infra/versions.tf sets no credentials, so if (2) is empty and AWS_PROFILE=hrl-mfa, the
provider uses exactly the profile checked here.
"""
import argparse
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3

ap = argparse.ArgumentParser()
ap.add_argument("--profile", default="hrl-mfa")
ap.add_argument("--min-minutes", type=int, default=15)
ap.add_argument("--expected-user", default=None, help="IAM user name to require (default: any IAM user)")
ap.add_argument("--provider-file", default=str(Path(__file__).resolve().parent.parent / "infra" / "versions.tf"))
args = ap.parse_args()

ok = True
def check(cond, msg):
    global ok
    print(("PASS  " if cond else "FAIL  ") + msg)
    ok &= bool(cond)

mask = lambda k: f"{k[:4]}************{k[-4:]}" if k else "none"

# 1. Nothing in the environment can override the profile (Terraform precedence step 2).
overrides = [v for v in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
                         "AWS_BEARER_TOKEN_BEDROCK", "ANTHROPIC_AWS_API_KEY") if os.environ.get(v)]
check(not overrides, f"no credential env vars that would override the profile ({overrides or 'none set'})")
env_profile = os.environ.get("AWS_PROFILE")
check(env_profile in (None, args.profile),
      f"AWS_PROFILE is unset or '{args.profile}' (currently: {env_profile or 'unset'})")

# 2. Provider block does not pin credentials or a different profile (precedence step 1).
src = Path(args.provider_file).read_text()
pinned = re.findall(r"^\s*(access_key|secret_key|token|profile|shared_credentials_files|assume_role)\b", src, re.M)
check(not pinned, f"Terraform provider block pins no credentials/profile ({pinned or 'none'})")

# 3. The profile resolves to temporary STS credentials with a session token.
import botocore.session  # noqa: E402  (does not resolve AWS_PROFILE, so a missing profile can't crash this check)
if args.profile not in botocore.session.Session().available_profiles:
    check(False, f"profile [{args.profile}] exists (create it with scripts/mfa_session.py)")
    print("\nRESULT: NOT READY")
    sys.exit(1)
sess = boto3.Session(profile_name=args.profile)
creds = sess.get_credentials()
frozen = creds.get_frozen_credentials() if creds else None
check(frozen is not None, f"profile [{args.profile}] has credentials (source: {getattr(creds, 'method', 'n/a')})")
if frozen:
    check(frozen.access_key.startswith("ASIA"), f"key ID is temporary STS (ASIA...): {mask(frozen.access_key)}")
    check(bool(frozen.token), "session token present")
    default = boto3.Session(profile_name="default").get_credentials()
    dkey = default.get_frozen_credentials().access_key if default else None
    check(frozen.access_key != dkey, f"differs from long-lived default key {mask(dkey)}")

# 4. The session is valid and belongs to the expected user (same ARN as the reviewed plan).
try:
    ident = sess.client("sts").get_caller_identity()
    check(":user/" in ident["Arn"] and (args.expected_user is None or ident["Arn"].endswith(f":user/{args.expected_user}")),
          f"caller identity is an IAM user{' named ' + args.expected_user if args.expected_user else ''}")
except Exception as e:  # expired or invalid
    check(False, f"sts:GetCallerIdentity failed: {type(e).__name__}: {str(e)[:120]}")

# 5. Remaining lifetime.
exp_file = Path.home() / ".aws" / f"{args.profile}.expiry"
if exp_file.exists():
    exp = datetime.fromisoformat(exp_file.read_text().strip())
    mins = (exp - datetime.now(timezone.utc)).total_seconds() / 60
    check(mins >= args.min_minutes, f"session valid for {mins:.0f} more minutes (expires {exp:%H:%M} UTC)")
else:
    check(False, f"expiry file {exp_file} not found (create the session with scripts/mfa_session.py)")

print("\nRESULT:", "READY - commands run with AWS_PROFILE=%s use the MFA session" % args.profile if ok else "NOT READY")
sys.exit(0 if ok else 1)
