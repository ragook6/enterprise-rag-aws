# Security design and publishing hygiene

## Identity and access

| Principal | Allowed | Explicitly not allowed (verified with the IAM policy simulator) |
|---|---|---|
| KB service role (one per KB) | `s3:ListBucket` on the documents bucket; `s3:GetObject` on `documents/*`; `bedrock:InvokeModel` on Titan V2; `s3vectors:Put/Get/Delete/QueryVectors`, `GetIndex` on **its own** index | other prefixes, writing objects, the other KB's index, deleting indexes, invoking generation models, `iam:PassRole` |
| KB role trust | `bedrock.amazonaws.com` with `aws:SourceAccount` = the account and `aws:SourceArn` = that KB (phase 2; `knowledge-base/*` in the account until the KB exists) | any other service or KB |
| Runner role | `bedrock:Retrieve` and ingestion-job actions on the two KB ARNs; `bedrock:InvokeModel(WithResponseStream)` on the `us.amazon.nova-micro-v1:0` profile and on the underlying model in 3 US Regions **only when** `bedrock:InferenceProfileArn` equals that profile | other models or profiles, calling the model directly, other KBs, S3/S3 Vectors data access, IAM, model agreements |
| Runner role trust | named IAM principal(s) with `aws:MultiFactorAuthPresent = true` | sessions without MFA |

Verification performed during the project: IAM Access Analyzer `ValidatePolicy` (0 findings) and `CheckNoPublicAccess`
(pass) on every policy; policy-simulator allow/deny matrices; and an empirical least-privilege test - assuming the runner
role with a restrictive **session policy** (effective permissions = role policy intersected with session policy) proved
that `Retrieve` does not need caller-side `InvokeModel` on the embedding model, without changing IAM.

## Credentials

- Day-to-day work used a 1-hour STS session obtained with MFA (`scripts/mfa_session.py`); scripts verify the session first.
- Scripts refuse to run when `AWS_BEARER_TOKEN_BEDROCK`, `ANTHROPIC_AWS_API_KEY` or `ANTHROPIC_API_KEY` is set.
- Terraform reads credentials from the environment/profile; the provider block pins none, so state contains no credentials.
- `iam/` contains optional drafts (placeholder account) for enforcing MFA on an IAM user and for a scoped deployer role.
  A deployer that can write role policies can escalate privileges unless a permissions boundary is enforced.

## Data protection

S3: SSE-S3, Block Public Access (all four), bucket-owner-enforced ownership, TLS-only bucket policy. S3 Vectors: SSE-S3.
The dashboard binds to `127.0.0.1`, disables usage statistics and imports no AWS SDK.

## What is never published

| Item | Handling |
|---|---|
| Terraform state, plans, `terraform.tfvars` | git-ignored |
| Original evaluation results (contain account and resource IDs) | git-ignored in `results/`; publish `results-public/` |
| Raw console screenshots | git-ignored in `screenshots-raw/` |
| Personal setup notes, reviewed Marketplace offer | git-ignored in `private/` |
| Local list of real identifiers used by the scanner | git-ignored `.sensitive-denylist` |

## Sanitized results

`scripts/docs/export_public_results.py` copies `results/` to `results-public/`, replacing the account ID with the AWS
documentation example `111122223333`, Knowledge Base IDs with `KBFIXED001` / `KBHIER0001`, and request IDs with null.
It fails if any non-identifier field differs from the original, if any denylisted value remains, or if the originals
change. `tests/test_public_results.py` re-checks this.

## Screenshot redaction

`scripts/docs/redact_image.py` (raw files are never modified):

1. **Crop first** - remove the console header/account menu and anything outside the evidence.
2. **Fill** remaining sensitive regions with solid pixels (pixel values are overwritten; no overlays or layers).
3. **Rebuild and re-encode** the image from raw RGB bytes into a new PNG with no metadata (EXIF/XMP/text/ICC).
4. Verify fills and metadata; write `MANIFEST.json` with output hashes and review status.
5. **Manually review every output image** before publication (no OCR tool is used).

## Pre-publication scanning

```bash
.venv/bin/python scripts/security/scan_public.py          # custom checks on every file selected for publication
.venv/bin/detect-secrets scan --baseline .secrets.baseline $(git ls-files | grep -vE '\.(pdf|png)$')   # generic detection
# .secrets.baseline lists 22 audited false positives (SHA-256 integrity hashes, config fingerprints, and the
# literal 'offline' test credential); any new finding is reported as unaudited.
```

The custom scanner checks the staged/candidate files for: values in `.sensitive-denylist`, AWS access-key patterns,
private keys, 12-digit account IDs other than the documentation placeholder and the fictional IDs in the synthetic
documents, IAM/STS ARNs with real accounts, e-mail addresses outside example domains, local home-directory paths,
image metadata, and forbidden files (state, tfvars, raw screenshots).
