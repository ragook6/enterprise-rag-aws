# Optional IAM hardening drafts

These policies are **not applied by Terraform**. They use the AWS documentation placeholder account `111122223333` and
`YOUR_IAM_USER`; replace both before use. All three validated with IAM Access Analyzer (0 findings).

| File | Purpose |
|---|---|
| `require-mfa-policy.json` | Attach to an IAM user so that, without an MFA session, its long-lived keys can only call `sts:GetSessionToken` and manage their own MFA |
| `deployer-trust-policy.json` | Trust for a dedicated deployment role: named user, MFA present, MFA age < 1 hour |
| `deployer-policy.json` | Permissions this Terraform needs, scoped to `hrl-rag-*` resources |

**Limitation:** any principal that can write IAM role policies can escalate privileges (create a role with an admin
inline policy and assume it). Enforce a permissions boundary on created roles before relying on the deployer role.
