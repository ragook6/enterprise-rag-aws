# AWS Console screenshot checklist

**Status: screenshots are added one at a time; the Status column shows which are captured, redacted and reviewed.** Images are added to `docs/images/aws/`
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
| 01 | [`01-bedrock-titan-embeddings.png`](../images/aws/01-bedrock-titan-embeddings.png) | Amazon Bedrock -> Model catalog -> Titan Text Embeddings V2 | Model card and availability | Embedding model used by both KBs | Captured, redacted, reviewed |
| 02 | [`02-bedrock-nova-micro-profile.png`](../images/aws/02-bedrock-nova-micro-profile.png) | Amazon Bedrock -> Model catalog -> Nova Micro | Model ID `amazon.nova-micro-v1:0`, Text -> Text, 128K max input | Generation model | Captured, redacted, reviewed |
| 03 | [`03-s3-documents-prefix.png`](../images/aws/03-s3-documents-prefix.png) | S3 -> documents bucket -> `documents/` | The 5 PDFs | Knowledge Base data source | Captured, redacted, reviewed |
| 04 | [`04-s3-permissions.png`](../images/aws/04-s3-permissions.png) | S3 -> bucket -> Permissions | Block Public Access (all on) + bucket policy (TLS-only) | Data protection | Captured, redacted, reviewed |
| 05 | [`05-s3-encryption.png`](../images/aws/05-s3-encryption.png) | S3 -> bucket -> Properties | Default encryption SSE-S3 | Encryption at rest | Captured, redacted, reviewed |
| 06 | [`06-s3-vector-bucket.png`](../images/aws/06-s3-vector-bucket.png) | S3 -> Vector buckets -> vector bucket -> Vector indexes | Vector bucket with its 2 indexes (bucket name and ARNs redacted) | S3 Vectors store | Captured, redacted, reviewed |
| 07 | [`07-s3-vector-indexes.png`](../images/aws/07-s3-vector-indexes.png) | S3 Vectors -> vector bucket -> index `baseline-fixed100-titanv2-1024` | Dimension 1024, cosine, enhanced index mode, non-filterable keys `AMAZON_BEDROCK_TEXT` / `AMAZON_BEDROCK_METADATA` (ARN redacted) | Index design (both indexes are created identically by Terraform) | Captured, redacted, reviewed |
| 08 | [`08-bedrock-knowledge-bases.png`](../images/aws/08-bedrock-knowledge-bases.png) | Amazon Bedrock -> Knowledge Bases | Both KBs `Available`, 1 data source each | Two experiment arms | Captured, redacted, reviewed |
| 09 | [`09-kb-fixed-overview.png`](../images/aws/09-kb-fixed-overview.png) | Fixed-size KB -> Overview | KB overview (ID redacted): status, description, service role name, RAG type vector store, data source with fixed-size chunking, tags | KB configuration | Captured, redacted, reviewed |
| 10 | [`10-kb-fixed-chunking.png`](../images/aws/10-kb-fixed-chunking.png) | Fixed-size KB -> Data source | Chunking strategy "Fixed-size chunking" (token values not expanded), default parsing, sync history (Complete, 5 scanned / 5 added / 0 failed), 5 documents INDEXED (IDs and S3 URIs redacted) | Strategy A; also covers #12 for the fixed-size side | Captured, redacted, reviewed |
| 11 | [`11-kb-hierarchical-chunking.png`](../images/aws/11-kb-hierarchical-chunking.png) | Hierarchical KB -> Data source | Hierarchical chunking popup: max parent 1500, max child 300, overlap 60; sync history (Complete, 5 scanned / 5 added / 0 failed), 5 documents INDEXED (IDs and S3 URIs redacted) | Strategy B; also covers #12 for the hierarchical side | Captured, redacted, reviewed |
| 12 | - | Each data source -> Sync history | Completed jobs with 5 documents indexed | Ingestion | Covered by #10 and #11 (no separate image) |
| 13 | [`13-iam-kb-role-trust.png`](../images/aws/13-iam-kb-role-trust.png) | IAM -> Roles -> `hrl-rag-kb-baseline-fixed100` -> Trust relationships | `bedrock.amazonaws.com`, `sts:AssumeRole`, `StringEquals aws:SourceAccount` and `ArnEquals aws:SourceArn` (values redacted) | Confused-deputy protection | Captured, redacted, reviewed |
| 14a | [`14a-iam-runner-trust.png`](../images/aws/14a-iam-runner-trust.png) | IAM -> Roles -> `hrl-rag-experiment-runner` -> Trust relationships | One named IAM user principal, `Bool aws:MultiFactorAuthPresent = true` (account ID and user name redacted) | MFA required to assume | Captured, redacted, reviewed |
| 14b | [`14b-iam-runner-permissions.png`](../images/aws/14b-iam-runner-permissions.png) | IAM -> Policies -> `hrl-rag-experiment-runner` -> Permissions (JSON) | `bedrock:Retrieve` and ingestion actions on exactly two `knowledge-base/` ARNs; `InvokeModel` on `inference-profile/us.amazon.nova-micro-v1:0` (account and KB IDs redacted; the final statement is below the visible area) | Least privilege | Captured, redacted, reviewed |
| 15 | [`15-cloudtrail-runner-calls.png`](../images/aws/15-cloudtrail-runner-calls.png) | CloudTrail -> Event history -> one `Converse` event | `AssumedRole` session `rag-evaluation` of `hrl-rag-experiment-runner`, `mfaAuthenticated: true`, `bedrock.amazonaws.com`, us-west-2 (access key, IP, event/request IDs, role IDs, account IDs redacted) | Evaluation ran as the MFA-gated runner role | Captured, redacted, reviewed |
| 16 | `16-cost-explorer.png` | Billing and Cost Management -> Cost Explorer (daily, by service) | Bedrock and S3 costs for the run day | Actual cost | Not captured |

Optional: `17-iam-mfa-status.png` (IAM user -> Security credentials, only the "MFA assigned" indicator; crop everything else).

## Captions (for README / LinkedIn once captured)

| # | Caption |
|---|---|
| 01 | Titan Text Embeddings V2 produces the 1024-dimension embeddings for both Knowledge Bases. |
| 02 | Amazon Nova Micro (`amazon.nova-micro-v1:0`) writes the answers. The evaluation runner invokes it through the `us.` cross-Region inference profile configured in Terraform and IAM. |
| 03 | The five synthetic PDFs (fictional company) are the single shared data source for both strategies. |
| 04 | The documents bucket blocks all public access and denies non-TLS requests. |
| 05 | Objects are encrypted at rest with SSE-S3 (no customer-managed key charges). |
| 06 | One S3 vector bucket holds both indexes, one per chunking strategy - pay-per-use vector storage with no provisioned capacity. |
| 07 | The fixed-size index: 1024 dimensions, cosine distance, and Bedrock's text/metadata keys stored as non-filterable metadata. The hierarchical index uses the same Terraform definition, so only chunking differs. |
| 08 | Two Knowledge Bases, one per chunking strategy. |
| 09 | The fixed-size Knowledge Base: a vector-store KB with its own least-privilege service role and one S3 data source using fixed-size chunking. |
| 10 | Strategy A: fixed-size 100-token chunks with the minimum 1% overlap. |
| 11 | Strategy B: hierarchical chunking - 300-token children are searched, 1,500-token parents are returned. |
| 12 | Ingestion completed for all five documents (verified independently with a coverage check). |
| 13 | Each Knowledge Base role can be assumed only by Bedrock, from this account, for that one Knowledge Base. |
| 14a/b | The evaluation runner can only retrieve from the two KBs and invoke Nova Micro via the US profile, and requires MFA. |
| 15 | A CloudTrail record of one evaluation `Converse` call: made by an MFA-authenticated session of the least-privilege runner role, not an administrator. |
| 16 | The full 70-call evaluation cost about a cent; nothing in the design bills by the hour. |
