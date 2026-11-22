# Engineering decision log

A sanitized record of how the project was built: each step was planned, reviewed and approved before anything that
could change AWS resources or incur cost. Account identifiers, identities and resource IDs are intentionally omitted.

| # | Step | Decision / outcome | Evidence |
|---|---|---|---|
| 1 | Synthetic corpus | 5 PDFs + 35 questions for a fictional company; page numbers located automatically | `validate_dataset.py` passes |
| 2 | Vector store | S3 Vectors instead of OpenSearch Serverless: no idle hourly charges for a low-traffic experiment | cost table in `deployment.md` |
| 3 | Experiment design | change only chunking; 1% overlap because the API minimum is 1 | `experiment_config.json` |
| 4 | IaC review gate | `fmt`, `validate`, `plan` (24 to add), Checkov (0 failed), Access Analyzer (0 findings), policy simulator | before first apply |
| 5 | Credentials | MFA-backed 1-hour session; runner role requires MFA | `check_mfa_session.py` |
| 6 | Trust hardening | after creation, each KB role trusts only its own KB ARN (in-place update, verified by plan and read-back) | `kb_trust_source_arns` |
| 7 | Ingestion data loss | first fixed-size ingestion: `COMPLETE`, 0 failed, but an "internal error" reason and one PDF at 90.2% coverage (6 chunks missing). Re-sync skipped unchanged files. **Decision:** replace the data source (deletes its vectors) and re-ingest | coverage 100%, 130 vectors, hierarchical KB untouched |
| 8 | Generation model | planned Claude model required an AWS Marketplace agreement; calls returned "not available for this account". An endpoint/model-ID mismatch also produced a 404 (no charge). **Decision:** switch to Amazon Nova Micro (first-party, no agreement) | single connectivity call succeeded |
| 9 | Least-privilege proof | session-policy tests showed which permissions calls really need; runner policy narrowed to Nova Micro via the US profile; unused statements removed | Access Analyzer + simulator |
| 10 | Q18 end-to-end test | both strategies correct; revealed hierarchical page-label issue | passage-evidence metric added |
| 11 | Full evaluation | 70/70 items, 0 errors, $0.00646 tracked; cost guard on projected and actual cost | `results-public/20261121T231031Z` |
| 12 | Scoring audit | hyphenation and unrequested keywords caused false negatives; v2 scoring added without altering originals | `rescored_v2.*`, regression tests |
| 13 | Failure analysis | retrieval vs generation triage + separately labeled reviewer reading | `failure_analysis_20261121T231031Z.json` |
| 14 | Publishing | standalone repo, sanitized results, irreversible screenshot redaction, secret scanning, Apache-2.0 | `docs/security.md` |

## Open items

- Console screenshots: capture, redact and review (see `docs/screenshots/README.md`).
- Confirm actual costs in Cost Explorer.
- Teardown with `terraform destroy` and `verify_cleanup.py` after screenshots.
