# Deployment, operation and teardown

> Creates AWS resources that incur (small) charges. Read the whole page first. Identifiers below are placeholders.

## 1. Prerequisites

| Requirement | Notes |
|---|---|
| AWS account, Region `us-west-2` | Amazon Bedrock, Knowledge Bases and S3 Vectors available in the Region |
| Model access | `amazon.titan-embed-text-v2:0` (embeddings) and the `us.amazon.nova-micro-v1:0` inference profile (generation) |
| Deploying identity | permissions to create the resources in [architecture.md](architecture.md); an optional scoped deployer policy draft is in `iam/` |
| MFA | an authenticator-app (TOTP) device: CLI sessions need a 6-digit code (passkeys/security keys cannot supply one to the CLI) |
| Tools | Python 3 + `pip install -r requirements.txt`, Terraform >= 1.6 (AWS provider ~> 6.73 is pinned) |

Tested versions: Python 3.14.2, Terraform 1.6.6, AWS provider 6.73.0, boto3 1.44.9, Streamlit 1.67.0.

## 2. Short-lived credentials

```bash
.venv/bin/python scripts/mfa_session.py                    # writes a 1-hour session to profile [hrl-mfa]
AWS_PROFILE=hrl-mfa .venv/bin/python scripts/check_mfa_session.py
```

`mfa_session.py` uses the long-lived profile only to call `sts:GetSessionToken`, prompts for the code with hidden input,
and stores the temporary credentials in a separate profile. `check_mfa_session.py` is read-only and fails if
credential environment variables would override the profile, if the Terraform provider block pins credentials, or if
the session is not temporary / about to expire.

## 3. Configuration

Main variables (`infra/variables.tf`):

| Variable | Default | Purpose |
|---|---|---|
| `aws_region` | `us-west-2` | Region for all resources |
| `project_name` | `hrl-rag` | resource-name prefix and `Project` tag |
| `embedding_model_id` / `embedding_dimensions` | `amazon.titan-embed-text-v2:0` / `1024` | controlled variables (both KBs) |
| `experiments` | fixed-size 100/1% and hierarchical 1500/300/60 | the independent variable |
| `generation_inference_profile_id` | `us.amazon.nova-micro-v1:0` | runner permissions; only `us.` profiles are accepted |
| `create_runner_role` / `runner_require_mfa` | `true` / `true` | MFA-gated evaluation role |
| `runner_trusted_principal_arns` | `[]` (= the identity running Terraform) | who may assume the runner role |
| `kb_trust_source_arns` | `{}` | phase-2 hardening: each KB role trusts only its KB ARN |
| `budget_alert_email` / `budget_limit_usd` | `null` / `10` | optional monthly AWS Budget |

Template: [`infra/terraform.tfvars.example`](../infra/terraform.tfvars.example). Real `terraform.tfvars` and state are git-ignored.

## 4. Deploy

```bash
cd infra
terraform init
AWS_PROFILE=hrl-mfa terraform plan -out=plan.tfplan      # review: expect 24 to add
AWS_PROFILE=hrl-mfa terraform apply plan.tfplan          # creates resources; does NOT start ingestion
```

Phase 2 (optional, in-place update of the two KB service roles):

```bash
terraform output -json kb_trust_source_arns              # copy into terraform.tfvars as kb_trust_source_arns
AWS_PROFILE=hrl-mfa terraform plan -out=trust.tfplan     # expect 0 add / 2 change / 0 destroy
AWS_PROFILE=hrl-mfa terraform apply trust.tfplan
```

## 5. Ingest and verify

```bash
AWS_PROFILE=hrl-mfa .venv/bin/python scripts/run_ingestion.py                       # both KBs, as the runner role
AWS_PROFILE=hrl-mfa .venv/bin/python scripts/run_ingestion.py --arms baseline-fixed100
AWS_PROFILE=hrl-mfa .venv/bin/python scripts/check_index_coverage.py --min-coverage 0.97
```

Do not rely on the ingestion job statistics alone (see the troubleshooting table in the README). If coverage is low,
a re-sync will skip unchanged files; replace the affected data source instead:

```bash
cd infra && AWS_PROFILE=hrl-mfa terraform plan -replace='aws_bedrockagent_data_source.experiment["baseline-fixed100"]' -out=replace.tfplan
```

## 6. Evaluate

```bash
AWS_PROFILE=hrl-mfa .venv/bin/python scripts/run_evaluation.py --retrieval-only          # no model calls
AWS_PROFILE=hrl-mfa .venv/bin/python scripts/run_evaluation.py --questions Q18          # 2 model calls
AWS_PROFILE=hrl-mfa .venv/bin/python scripts/run_evaluation.py --max-cost-usd 0.25      # 35 x 2
.venv/bin/python scripts/rescore_results.py                                             # offline v2 rescoring
```

Outputs per run in `results/<UTC-timestamp>/`: `results.jsonl`, `summary.json`, `summary.md`, `run_metadata.json`,
and `rescored_v2.*`. To publish results, create the sanitized copy:
`.venv/bin/python scripts/docs/export_public_results.py` (writes `results-public/`).

## 7. Cost

| Item | Observed / estimated |
|---|---|
| Full evaluation, generation (Nova Micro, 70 calls) | **$0.00646** tracked from API token usage |
| Embeddings (ingestion + queries), S3, S3 Vectors | estimated well under $0.01; not yet confirmed in Cost Explorer |
| Idle | storage only (a few MB); no hourly charges |

Prices used by the runner: Nova Micro on-demand $0.035 / $0.14 per million input / output tokens (us-west-2 Price List at the time of the run).

## 8. Teardown

```bash
cd infra && AWS_PROFILE=hrl-mfa terraform destroy        # removes all 24 resources; data sources delete their vectors
cd .. && AWS_PROFILE=hrl-mfa .venv/bin/python scripts/verify_cleanup.py   # read-only; non-zero exit if anything remains
```

Model access agreements you accepted in the account are not Terraform resources and are not removed by `destroy`.
