# AWS Console screenshot checklist

**Status: none of the AWS Console screenshots below has been captured yet.** Images are added to `docs/images/aws/`
only after they are captured, redacted with `scripts/docs/redact_image.py`, and reviewed. Dashboard screenshots (rendered
locally from sanitized results) are already in `docs/images/dashboard/`.

## Workflow

1. Capture in Region `us-west-2` while the resources exist. Save raw files to `screenshots-raw/NN-name.png` (git-ignored).
2. Add an entry per file to `screenshots-raw/redactions.json` - prefer `crop` (remove the console header with the account
   menu, the left navigation and anything irrelevant), then `boxes` for remaining sensitive regions:
   ```json
   {"03-s3-documents-prefix.png": {"crop": [0, 120, 1920, 1000], "boxes": [[260, 40, 900, 72]], "reviewed_by": ""}}
   ```
3. `.venv/bin/python scripts/docs/redact_image.py --spec screenshots-raw/redactions.json`
4. Open every output in `docs/images/aws/`, check against the redaction list, then set `reviewed_by` and re-run.
5. Run `scripts/security/scan_public.py` (image metadata check) before staging.

**Always redact:** the account ID / alias and IAM user name (console header), 12-digit numbers, ARNs, Knowledge Base,
data-source, job and index identifiers, bucket names containing the account ID, IP addresses, request/event IDs,
session names, e-mail addresses, MFA device names. **Do not capture** access keys, the IAM user's security-credentials
page with key IDs, billing contact details, or the "Test knowledge base" panel (it runs retrieval and incurs cost).

## Checklist

| # | File | Service -> console page | Capture | Demonstrates | Status |
|---|---|---|---|---|---|
| 01 | `01-bedrock-titan-embeddings.png` | Amazon Bedrock -> Model catalog -> Titan Text Embeddings V2 | Model card and availability | Embedding model used by both KBs | Not captured |
| 02 | `02-bedrock-nova-micro-profile.png` | Amazon Bedrock -> Cross-Region inference -> `us.amazon.nova-micro-v1:0` | Profile and its 3 US Regions | Generation model and US-only routing | Not captured |
| 03 | `03-s3-documents-prefix.png` | S3 -> documents bucket -> `documents/` | The 5 PDFs | Knowledge Base data source | Not captured |
| 04 | `04-s3-permissions.png` | S3 -> bucket -> Permissions | Block Public Access (all on) + bucket policy (TLS-only) | Data protection | Not captured |
| 05 | `05-s3-encryption.png` | S3 -> bucket -> Properties | Default encryption SSE-S3 | Encryption at rest | Not captured |
| 06 | `06-s3-vector-bucket.png` | S3 -> Vector buckets -> vector bucket | Bucket and encryption | S3 Vectors store | Not captured |
| 07 | `07-s3-vector-indexes.png` | S3 Vectors -> indexes | Both indexes: 1024 dims, float32, cosine, non-filterable keys | Identical index design | Not captured |
| 08 | `08-bedrock-knowledge-bases.png` | Amazon Bedrock -> Knowledge Bases | Both KBs `Available` | Two experiment arms | Not captured |
| 09 | `09-kb-fixed-overview.png` | Fixed-size KB -> Overview | Embedding model, S3 Vectors store, service role name | KB configuration | Not captured |
| 10 | `10-kb-fixed-chunking.png` | Fixed-size KB -> Data source -> configuration | Chunking: fixed size, 100 tokens, 1% | Strategy A | Not captured |
| 11 | `11-kb-hierarchical-chunking.png` | Hierarchical KB -> Data source -> configuration | Chunking: hierarchical 1500 / 300 / 60 | Strategy B | Not captured |
| 12 | `12-kb-sync-history.png` | Each data source -> Sync history | Completed jobs with 5 documents indexed | Ingestion | Not captured |
| 13 | `13-iam-kb-role-trust.png` | IAM -> Roles -> KB service role -> Trust relationships | `ArnEquals aws:SourceArn` to one KB, `aws:SourceAccount` | Confused-deputy protection | Not captured |
| 14 | `14-iam-runner-role.png` | IAM -> Roles -> runner role | Trust (`aws:MultiFactorAuthPresent`) and permissions JSON | Least privilege + MFA | Not captured |
| 15 | `15-cloudtrail-runner-calls.png` | CloudTrail -> Event history, filter `Retrieve` / `InvokeModel` | Events by the assumed runner role | Evaluation ran with least privilege | Not captured |
| 16 | `16-cost-explorer.png` | Billing and Cost Management -> Cost Explorer (daily, by service) | Bedrock and S3 costs for the run day | Actual cost | Not captured |

Optional: `17-iam-mfa-status.png` (IAM user -> Security credentials, only the "MFA assigned" indicator; crop everything else).

## Captions (for README / LinkedIn once captured)

| # | Caption |
|---|---|
| 01 | Titan Text Embeddings V2 produces the 1024-dimension embeddings for both Knowledge Bases. |
| 02 | Nova Micro is invoked only through the US cross-Region inference profile, keeping inference in US Regions. |
| 03 | The five synthetic PDFs (fictional company) are the single shared data source for both strategies. |
| 04 | The documents bucket blocks all public access and denies non-TLS requests. |
| 05 | Objects are encrypted at rest with SSE-S3 (no customer-managed key charges). |
| 06 | One S3 vector bucket holds both indexes - pay-per-use vector storage with no provisioned capacity. |
| 07 | Both indexes are identical (1024-d, float32, cosine) so only chunking differs. |
| 08 | Two Knowledge Bases, one per chunking strategy. |
| 09 | Each Knowledge Base uses Titan V2, S3 Vectors and its own least-privilege service role. |
| 10 | Strategy A: fixed-size 100-token chunks with the minimum 1% overlap. |
| 11 | Strategy B: hierarchical chunking - 300-token children are searched, 1,500-token parents are returned. |
| 12 | Ingestion completed for all five documents (verified independently with a coverage check). |
| 13 | Each Knowledge Base role can be assumed only by Bedrock, from this account, for that one Knowledge Base. |
| 14 | The evaluation runner can only retrieve from the two KBs and invoke Nova Micro via the US profile, and requires MFA. |
| 15 | CloudTrail shows retrieval and model calls made by the MFA-gated runner role, not an administrator. |
| 16 | The full 70-call evaluation cost about a cent; nothing in the design bills by the hour. |
