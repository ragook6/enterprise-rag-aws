#!/usr/bin/env python3
"""
READ-ONLY check that no lab resources remain after `terraform destroy`.
Makes only List/Get calls. Exits 1 if anything is still present.

Usage: .venv/bin/python scripts/verify_cleanup.py [--project hrl-rag] [--region us-west-2]
"""
import argparse
import sys

import boto3
from botocore.exceptions import ClientError

ap = argparse.ArgumentParser()
ap.add_argument("--project", default="hrl-rag")
ap.add_argument("--region", default="us-west-2")
args = ap.parse_args()

s = boto3.Session(region_name=args.region)
account = s.client("sts").get_caller_identity()["Account"]
leftovers = []

# 1. Knowledge Bases
for kb in s.client("bedrock-agent").list_knowledge_bases(maxResults=100)["knowledgeBaseSummaries"]:
    if kb["name"].startswith(args.project):
        leftovers.append(f"Knowledge Base {kb['name']} ({kb['knowledgeBaseId']}) status={kb['status']}")

# 2. S3 vector buckets
for vb in s.client("s3vectors").list_vector_buckets().get("vectorBuckets", []):
    if vb["vectorBucketName"].startswith(args.project):
        leftovers.append(f"S3 vector bucket {vb['vectorBucketName']}")

# 3. Documents bucket
docs_bucket = f"{args.project}-docs-{account}-{args.region}"
try:
    s.client("s3").head_bucket(Bucket=docs_bucket)
    leftovers.append(f"S3 bucket {docs_bucket}")
except ClientError as e:
    if e.response["Error"]["Code"] not in ("404", "NoSuchBucket", "403"):
        raise

# 4. IAM roles and policies
iam = s.client("iam")
for page in iam.get_paginator("list_roles").paginate():
    leftovers += [f"IAM role {r['RoleName']}" for r in page["Roles"] if r["RoleName"].startswith(f"{args.project}-")]
for page in iam.get_paginator("list_policies").paginate(Scope="Local"):
    leftovers += [f"IAM policy {p['PolicyName']}" for p in page["Policies"] if p["PolicyName"].startswith(args.project)]

# 5. Anything else still carrying the Project tag (catches resources added later)
tagging = s.client("resourcegroupstaggingapi")
for page in tagging.get_paginator("get_resources").paginate(
        TagFilters=[{"Key": "Project", "Values": [args.project]}]):
    leftovers += [f"Tagged resource {r['ResourceARN']}" for r in page["ResourceTagMappingList"]]

if leftovers:
    print("Resources still present:")
    for item in sorted(set(leftovers)):
        print("  -", item)
    print("\nNote: the tagging API can lag a few minutes behind deletions.")
    sys.exit(1)
print(f"Clean: no '{args.project}' resources found in {args.region} (account {account}).")
