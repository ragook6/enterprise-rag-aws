#!/usr/bin/env python3
"""
Create a 1-hour MFA-authenticated AWS session and store it in a separate profile.

Run it YOURSELF in a terminal (it prompts for the 6-digit code without echoing it):
    .venv/bin/python scripts/mfa_session.py

What it does:
  1. Uses your long-lived keys (profile "default") ONLY to call sts:GetSessionToken.
  2. Sends the serial of your authenticator-app (TOTP) MFA device plus the code you type.
  3. Writes the temporary credentials (ASIA... key, secret, session token) to the
     [hrl-mfa] profile in ~/.aws/credentials (file mode 600) and region to ~/.aws/config.
  4. Prints only the expiry time and a masked key ID, never the secret or token.
Other profiles, including [default], are not modified.
"""
import argparse
import configparser
import getpass
import os
import stat
import sys
from datetime import timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--source-profile", default="default", help="profile holding the long-lived keys")
ap.add_argument("--target-profile", default="hrl-mfa", help="profile to write the session into")
ap.add_argument("--region", default="us-west-2")
ap.add_argument("--duration", type=int, default=3600, help="seconds (900-129600); default 1 hour")
ap.add_argument("--serial", help="MFA device ARN (auto-detected authenticator app if omitted)")
args = ap.parse_args()

if args.target_profile == args.source_profile:
    sys.exit("target profile must differ from the source profile")

src = boto3.Session(profile_name=args.source_profile, region_name=args.region)
user_arn = src.client("sts").get_caller_identity()["Arn"]
if ":user/" not in user_arn:
    sys.exit(f"Source profile must be an IAM user, got {user_arn}")
user_name = user_arn.split(":user/")[-1].split("/")[-1]

serial = args.serial
if not serial:
    devices = src.client("iam").list_mfa_devices(UserName=user_name)["MFADevices"]
    totp = [d["SerialNumber"] for d in devices if ":mfa/" in d["SerialNumber"]]
    if not totp:
        kinds = ", ".join(d["SerialNumber"].split(":")[-1].split("/")[0] for d in devices) or "none"
        sys.exit(
            "No authenticator-app (virtual/TOTP) MFA device found on this user "
            f"(found: {kinds}).\nPasskeys/security keys (u2f) cannot supply a CLI code. Add an "
            "'Authenticator app' MFA device in IAM -> Users -> Security credentials, then re-run.")
    if len(totp) > 1:
        sys.exit("Several TOTP devices found; pass one with --serial:\n  " + "\n  ".join(totp))
    serial = totp[0]

print(f"User   : {user_arn}")
print(f"Device : {serial}")
code = getpass.getpass("MFA code (input hidden): ").strip()
if not (code.isdigit() and len(code) == 6):
    sys.exit("The MFA code must be 6 digits.")

try:
    creds = src.client("sts").get_session_token(
        DurationSeconds=args.duration, SerialNumber=serial, TokenCode=code)["Credentials"]
except ClientError as e:
    sys.exit(f"GetSessionToken failed: {e.response['Error']['Code']} - {e.response['Error']['Message']}")
finally:
    del code

aws_dir = Path.home() / ".aws"
aws_dir.mkdir(mode=0o700, exist_ok=True)

cred_file = aws_dir / "credentials"
cp = configparser.RawConfigParser()
cp.read(cred_file)
if not cp.has_section(args.target_profile):
    cp.add_section(args.target_profile)
cp.set(args.target_profile, "aws_access_key_id", creds["AccessKeyId"])
cp.set(args.target_profile, "aws_secret_access_key", creds["SecretAccessKey"])
cp.set(args.target_profile, "aws_session_token", creds["SessionToken"])
with open(cred_file, "w") as fh:
    cp.write(fh)
os.chmod(cred_file, stat.S_IRUSR | stat.S_IWUSR)  # 600

cfg_file = aws_dir / "config"
cfg = configparser.RawConfigParser()
cfg.read(cfg_file)
section = f"profile {args.target_profile}"
if not cfg.has_section(section):
    cfg.add_section(section)
cfg.set(section, "region", args.region)
with open(cfg_file, "w") as fh:
    cfg.write(fh)

expiry = creds["Expiration"].astimezone(timezone.utc)
(aws_dir / f"{args.target_profile}.expiry").write_text(expiry.isoformat() + "\n")

key = creds["AccessKeyId"]
print(f"\nStored temporary credentials in profile [{args.target_profile}]")
print(f"Key ID : {key[:4]}************{key[-4:]}  (ASIA = temporary STS credentials)")
print(f"Expires: {expiry:%Y-%m-%d %H:%M:%S} UTC")
print(f"\nUse it with:  export AWS_PROFILE={args.target_profile}")
