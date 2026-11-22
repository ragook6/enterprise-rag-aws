"""
Synthetic enterprise document content for RAG testing.

All organizations, people, account IDs, resource IDs, IP addresses and
contracts in this file are FICTIONAL. "Halcyon Ridge Logistics" (HRL) and
"Cobalt Arc Consulting" do not exist. Public IPs use RFC 5737 documentation
ranges (198.51.100.0/24, 203.0.113.0/24).

Content DSL (consumed by generate_pdfs.py):
  ("h1", text)              numbered section heading
  ("h2", text)              sub-heading
  ("p", text)               paragraph; **bold** supported; text is XML-escaped
  ("bullets", [text, ...])  bulleted list
  ("steps", [text, ...])    numbered procedure steps
  ("table", rows, widths)   first row is the header; widths in inches
  ("code", text)            monospaced block
  ("note", text)            shaded call-out box
  ("pagebreak",)
"""

ORG = "Halcyon Ridge Logistics, Inc."
ORG_SHORT = "HRL"
DISCLAIMER = ("SYNTHETIC TEST DOCUMENT - Halcyon Ridge Logistics is a fictional "
              "organization. All names, account IDs and resources are invented.")

# ---------------------------------------------------------------------------
# 1. AWS Landing Zone Architecture
# ---------------------------------------------------------------------------
LANDING_ZONE = {
    "filename": "AWS_Landing_Zone_Architecture.pdf",
    "doc_id": "HRL-ARC-001",
    "title": "AWS Landing Zone Architecture",
    "subtitle": "Multi-account foundation for Project Meridian",
    "version": "2.3",
    "date": "2026-01-19",
    "owner": "Daniel Okafor, Principal Cloud Architect",
    "body": [
        ("h1", "Document Control"),
        ("table", [
            ["Field", "Value"],
            ["Document ID", "HRL-ARC-001"],
            ["Version / Status", "2.3 / Approved"],
            ["Owner", "Daniel Okafor, Principal Cloud Architect, Cloud Platform Engineering (CPE)"],
            ["Approver", "Marisol Vega, VP Infrastructure and Program Sponsor"],
            ["Last review / Next review", "2026-01-19 / 2026-07-19"],
            ["Related documents", "HRL-NET-002 Transit Gateway Design; HRL-SEC-003 IAM Security Policies; "
                                  "HRL-OPS-004 Lambda Incident Runbook; SOW-HRL-2026-017 Cloud Migration SOW"],
        ], [1.8, 4.9]),
        ("h1", "Purpose and Scope"),
        ("p", "This document defines the target-state AWS landing zone for Halcyon Ridge Logistics (HRL). "
              "The landing zone is the governed multi-account foundation onto which 160 applications will be "
              "migrated from the Dayton data center (DC-DAY1) under Project Meridian, as contracted in "
              "SOW-HRL-2026-017. It covers the organization structure, account inventory, region strategy, "
              "centralized logging, account vending, backup and the tagging standard. Network routing details "
              "are delegated to HRL-NET-002 and identity controls are delegated to HRL-SEC-003."),
        ("p", "The landing zone is deployed with AWS Control Tower landing zone version 3.3 and is managed "
              "from the hrl-management account (604318275519). All foundational resources are defined as "
              "Terraform code in the repository hrl-platform-foundation and changes are applied only through "
              "the CPE deployment pipeline; console changes to foundational resources are prohibited."),
        ("h1", "Design Principles"),
        ("bullets", [
            "**Account as the blast-radius boundary:** every workload environment receives its own AWS account; "
            "production and non-production never share an account.",
            "**Centralized security, decentralized delivery:** guardrails are enforced centrally with SCPs and "
            "Control Tower controls, while application teams own their workload accounts.",
            "**Immutable audit trail:** all API activity and configuration history is written to the "
            "hrl-log-archive account, which no workload team can modify.",
            "**Two regions only:** workloads run in us-east-2 (Ohio) with disaster recovery in us-west-2 (Oregon).",
            "**Everything as code:** accounts, guardrails and baselines are provisioned through Terraform and "
            "Account Factory for Terraform (AFT).",
        ]),
        ("h1", "Organization Structure"),
        ("p", "The AWS Organization uses six top-level organizational units (OUs). Service control policies "
              "(SCPs) are attached at the OU level; the full SCP catalog is defined in HRL-SEC-003 section 7."),
        ("table", [
            ["OU", "Purpose", "Key SCPs"],
            ["Security", "Log archive and security tooling accounts", "deny-leave-org, protect-security-services"],
            ["Infrastructure", "Network hub and shared services", "deny-regions, deny-root"],
            ["Workloads/Prod", "Production application accounts", "deny-regions, require-imdsv2, deny-root"],
            ["Workloads/NonProd", "Development and test accounts", "deny-regions, require-imdsv2"],
            ["Sandbox", "Time-boxed experimentation", "sandbox-guardrails, deny-regions"],
            ["Suspended", "Closed or quarantined accounts", "deny-all"],
        ], [1.5, 2.8, 2.4]),
        ("h2", "Core Account Inventory"),
        ("table", [
            ["Account name", "Account ID", "OU", "Purpose"],
            ["hrl-management", "604318275519", "Root", "Organizations, Control Tower, billing"],
            ["hrl-log-archive", "739204615882", "Security", "CloudTrail, Config and flow log storage"],
            ["hrl-security-tooling", "812475930164", "Security", "GuardDuty, Security Hub, Access Analyzer"],
            ["hrl-network-hub", "357120894463", "Infrastructure", "Transit Gateway, inspection, Direct Connect"],
            ["hrl-shared-services", "290563718845", "Infrastructure", "Identity Center admin, CI/CD, DNS"],
            ["hrl-prod-workloads", "538946102277", "Workloads/Prod", "Tier 1 and Tier 2 production apps"],
            ["hrl-nonprod-workloads", "671829350418", "Workloads/NonProd", "Dev and test environments"],
        ], [1.7, 1.2, 1.4, 2.4]),
        ("p", "The hrl-security-tooling account (812475930164) is the delegated administrator for Amazon "
              "GuardDuty, AWS Security Hub, Amazon Inspector and IAM Access Analyzer. The hrl-network-hub "
              "account (357120894463) owns all Transit Gateways and shares them to workload OUs using AWS RAM, "
              "as described in HRL-NET-002."),
        ("h1", "Region Strategy"),
        ("p", "HRL operates in exactly two AWS Regions. The primary Region is us-east-2 (Ohio), chosen for its "
              "proximity to the Columbus and Chicago Direct Connect locations. The disaster recovery Region is "
              "us-west-2 (Oregon). All other Regions are blocked by the SCP hrl-scp-deny-regions, with "
              "exemptions only for global services: IAM, AWS Organizations, Amazon Route 53, Amazon CloudFront, "
              "AWS Support and AWS Budgets."),
        ("p", "A new Region may be enabled only with written approval from the Security Architecture Review "
              "Board (SARB) and a minimum lead time of 20 business days to extend logging, guardrails and "
              "IPAM pools to that Region."),
        ("h1", "IP Address Plan"),
        ("p", "All AWS address space is allocated from the supernet 10.64.0.0/12 using Amazon VPC IP Address "
              "Manager (IPAM) in the hrl-network-hub account. Workload VPCs receive a /20 by default from the "
              "IPAM pool hrl-ipam-workloads. The on-premises Dayton data center uses 172.20.0.0/14 and must "
              "never be re-used in AWS."),
        ("table", [
            ["Block", "CIDR", "Region", "Usage"],
            ["Network hub", "10.64.0.0/16", "us-east-2", "Inspection VPC 10.64.0.0/22, egress VPC 10.64.4.0/22"],
            ["Shared services", "10.65.0.0/16", "us-east-2", "Directory, CI/CD runners, DNS resolvers"],
            ["Production", "10.66.0.0/16", "us-east-2", "Production workload VPCs (/20 each)"],
            ["Non-production", "10.72.0.0/16", "us-east-2", "Dev and test workload VPCs (/20 each)"],
            ["DR (all tiers)", "10.76.0.0/14", "us-west-2", "Pilot-light and warm-standby VPCs"],
            ["On-premises", "172.20.0.0/14", "Dayton DC", "Reserved; not routable inside AWS VPCs"],
        ], [1.3, 1.2, 1.0, 3.2]),
        ("p", "Connectivity between these blocks, including route-table segmentation and traffic inspection, "
              "is specified in HRL-NET-002 sections 4 and 5."),
        ("h1", "Centralized Logging and Monitoring"),
        ("p", "An organization-wide CloudTrail trail named hrl-org-trail captures management and S3 data events "
              "from every account. The trail delivers to the bucket hrl-org-cloudtrail-739204615882-use2 in the "
              "hrl-log-archive account (739204615882). The bucket uses S3 Object Lock in compliance mode with a "
              "400-day retention period. Objects transition to S3 Glacier Deep Archive after 400 days and are "
              "expired after 2,555 days (7 years) to satisfy HRL's financial records retention policy."),
        ("p", "AWS Config is enabled in all accounts and both Regions, with an organization aggregator named "
              "hrl-config-aggregator in the hrl-security-tooling account. VPC Flow Logs and Transit Gateway "
              "Flow Logs are delivered to the bucket hrl-network-flowlogs-739204615882-use2 with a 60-second "
              "aggregation interval and 365-day retention."),
        ("bullets", [
            "GuardDuty findings of severity 7.0 or higher are routed by EventBridge to the security on-call rotation.",
            "Security Hub runs the AWS Foundational Security Best Practices and CIS AWS Foundations v3.0 standards.",
            "CloudWatch Logs groups created by workloads must set a retention period; the default is 30 days.",
        ]),
        ("h1", "Account Vending with AFT"),
        ("p", "New accounts are requested by pull request to the repository hrl-aft-account-requests. Account "
              "Factory for Terraform (AFT) then creates the account in the requested OU and applies the HRL "
              "baseline. The service level for account vending is 2 business days from pull request approval. "
              "Each account request must include the CostCenter, Owner, Environment and DataClassification "
              "tags defined in section 10."),
        ("p", "The account baseline applied by AFT performs the following: deletes the default VPC in every "
              "Region, enables EBS encryption by default with the environment KMS key, enables S3 Block Public "
              "Access at the account level, allocates a /20 VPC from IPAM and attaches it to the Transit Gateway, "
              "creates an AWS Budgets alert, and assigns the standard Identity Center permission sets from "
              "HRL-SEC-003."),
        ("p", "Sandbox accounts have a maximum lifetime of 90 days and a monthly budget of USD 500. When "
              "actual spend reaches 120 percent of the sandbox budget the account is automatically moved to the "
              "Suspended OU. Non-production accounts have a default budget alert of USD 5,000 per month."),
        ("h1", "Backup and Disaster Recovery"),
        ("p", "AWS Backup is managed centrally through organization backup policies. Recovery objectives are "
              "assigned per application tier, and the tier definitions (RTO and RPO) are contractually defined "
              "in SOW-HRL-2026-017 section 7."),
        ("table", [
            ["Backup plan", "Schedule", "Retention", "Cross-region copy"],
            ["hrl-backup-tier1", "Hourly + daily", "Daily 35 days, monthly 13 months", "Yes, to us-west-2"],
            ["hrl-backup-tier2", "Daily", "Daily 35 days, monthly 13 months", "Yes, to us-west-2"],
            ["hrl-backup-tier3", "Daily", "Daily 14 days", "No"],
        ], [1.5, 1.3, 2.4, 1.5]),
        ("p", "Tier 1 workloads use the hrl-backup-tier1 plan, which takes hourly snapshots and copies every "
              "recovery point to a vault in us-west-2 that is locked with AWS Backup Vault Lock. DR tests are "
              "performed twice per year, in April and October."),
        ("h1", "Tagging Standard"),
        ("p", "The following tags are mandatory on all taggable resources. They are enforced by an AWS "
              "Organizations tag policy and by the Control Tower proactive control for Terraform plans."),
        ("table", [
            ["Tag key", "Allowed values / format", "Example"],
            ["CostCenter", "CC- followed by 4 digits", "CC-4410"],
            ["Owner", "Team distribution list", "cpe-team@hrl.example"],
            ["Environment", "prod, nonprod, sandbox, shared", "prod"],
            ["DataClassification", "public, internal, confidential, restricted", "confidential"],
            ["AppId", "APP- followed by 4 digits", "APP-0217"],
        ], [1.6, 3.0, 2.1]),
        ("h1", "Change Management"),
        ("p", "Changes to foundational resources are reviewed by the Change Advisory Board (CAB), which meets "
              "weekly on Tuesdays at 14:00 ET. Any change to an SCP, to the organization CloudTrail trail or to "
              "Transit Gateway route tables additionally requires approval from the Security Architecture "
              "Review Board (SARB). Emergency changes may be applied with approval from the on-call Incident "
              "Commander and must be ratified by the CAB within 2 business days."),
    ],
}

# ---------------------------------------------------------------------------
# 2. Transit Gateway Design
# ---------------------------------------------------------------------------
TRANSIT_GATEWAY = {
    "filename": "Transit_Gateway_Design.pdf",
    "doc_id": "HRL-NET-002",
    "title": "Transit Gateway Network Design",
    "subtitle": "Hub-and-spoke connectivity, inspection and hybrid networking",
    "version": "1.6",
    "date": "2026-02-09",
    "owner": "Aiko Brennan, Lead Network Architect",
    "body": [
        ("h1", "Document Control"),
        ("table", [
            ["Field", "Value"],
            ["Document ID", "HRL-NET-002"],
            ["Version / Status", "1.6 / Approved"],
            ["Owner", "Aiko Brennan, Lead Network Architect, Cloud Platform Engineering (CPE)"],
            ["Approver", "Security Architecture Review Board (SARB), decision SARB-2026-011"],
            ["Parent document", "HRL-ARC-001 AWS Landing Zone Architecture"],
            ["Related documents", "HRL-SEC-003 IAM Security Policies; HRL-OPS-004 Lambda Incident Runbook"],
        ], [1.8, 4.9]),
        ("h1", "Overview"),
        ("p", "HRL uses a hub-and-spoke network built on AWS Transit Gateway (TGW). All Transit Gateways are "
              "owned by the hrl-network-hub account (357120894463) and shared to the Workloads and "
              "Infrastructure OUs through the AWS RAM resource share hrl-ram-tgw-share. Every VPC-to-VPC, "
              "VPC-to-internet and VPC-to-on-premises flow traverses a centralized inspection VPC running AWS "
              "Network Firewall. Address allocations referenced here come from the IP plan in HRL-ARC-001 "
              "section 6."),
        ("h1", "Transit Gateway Configuration"),
        ("table", [
            ["Setting", "Primary (us-east-2)", "DR (us-west-2)"],
            ["Name", "hrl-tgw-use2-01", "hrl-tgw-usw2-01"],
            ["TGW ID", "tgw-0c4e8a19d27b3f5a6", "tgw-07d2b9e41fa6c3085"],
            ["Amazon side ASN", "64620", "64621"],
            ["Default route table association", "Disabled", "Disabled"],
            ["Default route table propagation", "Disabled", "Disabled"],
            ["Auto accept shared attachments", "Disabled", "Disabled"],
            ["DNS support / VPN ECMP", "Enabled / Enabled", "Enabled / Enabled"],
            ["Multicast", "Disabled", "Disabled"],
        ], [2.5, 2.1, 2.1]),
        ("p", "The primary Transit Gateway hrl-tgw-use2-01 uses Amazon side ASN 64620 and the DR Transit Gateway "
              "hrl-tgw-usw2-01 uses Amazon side ASN 64621. Default route table association and propagation are "
              "disabled on both gateways so that every attachment must be explicitly placed into a segment; this "
              "prevents a newly shared VPC from gaining unintended reachability."),
        ("h1", "Attachments and Segments"),
        ("table", [
            ["Attachment", "CIDR", "Attachment ID", "Associated route table"],
            ["vpc-inspection-use2", "10.64.0.0/22", "tgw-attach-0a17c3e9b52d84f61", "tgw-rt-inspection"],
            ["vpc-egress-use2", "10.64.4.0/22", "tgw-attach-0b28d4f0c63e95a72", "tgw-rt-shared"],
            ["vpc-shared-svcs-use2", "10.65.0.0/16", "tgw-attach-0c39e5a1d74fa6b83", "tgw-rt-shared"],
            ["vpc-prod-orders-use2", "10.66.0.0/20", "tgw-attach-0d4af6b2e85ab7c94", "tgw-rt-prod"],
            ["vpc-prod-analytics-use2", "10.66.16.0/20", "tgw-attach-0e5ba7c3f96bc8da5", "tgw-rt-prod"],
            ["vpc-nonprod-dev-use2", "10.72.0.0/20", "tgw-attach-0f6cb8d4a07cd9eb6", "tgw-rt-nonprod"],
            ["dxgw-hrl-dxgw-01", "172.20.0.0/14", "tgw-attach-01d7e9f5b18dea0c7", "tgw-rt-onprem"],
            ["vpn-dayton-backup", "172.20.0.0/14", "tgw-attach-02e8fa06c29efb1d8", "tgw-rt-onprem"],
        ], [1.75, 1.05, 2.25, 1.65]),
        ("p", "The production order-processing VPC vpc-prod-orders-use2 (10.66.0.0/20) belongs to the "
              "hrl-prod-workloads account and is associated with the route table tgw-rt-prod. This VPC hosts "
              "the Order Event Processor Lambda function described in HRL-OPS-004."),
        ("h1", "Route Table Design"),
        ("p", "Five Transit Gateway route tables implement network segmentation. Spoke route tables contain only "
              "a default route to the inspection attachment, which forces all east-west and north-south traffic "
              "through AWS Network Firewall. Production and non-production spokes never propagate into each "
              "other's route tables, and the firewall policy also denies traffic between 10.66.0.0/16 and "
              "10.72.0.0/16 as a second layer of isolation."),
        ("table", [
            ["Route table", "Associations", "Propagations", "Static routes"],
            ["tgw-rt-prod", "Production VPCs", "None", "0.0.0.0/0 to inspection attachment"],
            ["tgw-rt-nonprod", "Non-production VPCs", "None", "0.0.0.0/0 to inspection attachment"],
            ["tgw-rt-shared", "Shared services, egress", "None", "0.0.0.0/0 to inspection attachment"],
            ["tgw-rt-onprem", "DX gateway, VPN", "None", "10.64.0.0/12 to inspection attachment"],
            ["tgw-rt-inspection", "Inspection VPC", "All spokes, DX, VPN", "0.0.0.0/0 to egress attachment"],
        ], [1.4, 1.7, 1.5, 2.1]),
        ("h1", "Centralized Inspection"),
        ("p", "The inspection VPC vpc-inspection-use2 hosts the AWS Network Firewall hrl-nfw-use2 with firewall "
              "endpoints in three Availability Zones: us-east-2a, us-east-2b and us-east-2c. Appliance mode is "
              "enabled on the inspection VPC attachment tgw-attach-0a17c3e9b52d84f61. Appliance mode keeps both "
              "directions of a flow pinned to the same Availability Zone firewall endpoint, which is required "
              "for symmetric routing; without it, stateful inspection drops return traffic."),
        ("p", "The firewall policy hrl-nfw-policy-baseline uses the stateful rule group hrl-stateful-baseline "
              "with a capacity of 3,000 rules and strict rule ordering. Internet egress is restricted to a "
              "domain allowlist managed in the rule group hrl-egress-domain-allowlist. Firewall alert and flow "
              "logs are sent to the hrl-log-archive account."),
        ("h1", "Hybrid Connectivity"),
        ("h2", "AWS Direct Connect"),
        ("p", "HRL has two dedicated 10 Gbps AWS Direct Connect connections terminating at Colo Site A in "
              "Columbus (dxcon-fh41a7c2) and Colo Site B in Chicago (dxcon-fg92b8d3). Both connections attach to "
              "the Direct Connect gateway hrl-dxgw-01 (ASN 64630) through transit virtual interfaces, and the "
              "gateway is associated with hrl-tgw-use2-01. The allowed prefixes advertised to on-premises are "
              "10.64.0.0/12. The on-premises routers use BGP ASN 65010. BFD is enabled with a 300 ms interval "
              "and a multiplier of 3."),
        ("h2", "Site-to-Site VPN Backup"),
        ("p", "A Site-to-Site VPN with two IPsec tunnels to the Dayton firewall public IP 198.51.100.24 provides "
              "backup connectivity. To keep Direct Connect preferred, the on-premises routers prepend AS 65010 "
              "three times on all prefixes advertised over the VPN. With BFD on Direct Connect, failover to the "
              "VPN is expected to complete in under 60 seconds. VPN throughput is limited to approximately "
              "1.25 Gbps per tunnel, so Tier 3 batch transfers are paused during a Direct Connect outage."),
        ("h1", "Inter-Region Peering"),
        ("p", "The primary and DR Transit Gateways are connected by the peering attachment "
              "tgw-attach-03f90b17d3af0c2e9. Transit Gateway peering does not support dynamic propagation, so "
              "static routes are configured: 10.76.0.0/14 points to the peering attachment in us-east-2, and "
              "10.64.0.0/14 points to the peering attachment in us-west-2. Cross-region replication for Tier 1 "
              "databases and AWS Backup copies to us-west-2 use this path."),
        ("h1", "MTU, Capacity and Monitoring"),
        ("bullets", [
            "MTU is 8500 bytes for VPC, Direct Connect and peering attachments and 1500 bytes for VPN attachments.",
            "Capacity alarm: any Direct Connect connection above 7 Gbps (70 percent of 10 Gbps) for 15 minutes "
            "raises a SEV3 capacity ticket.",
            "The CloudWatch alarm hrl-tgw-blackhole-drops fires when PacketDropCountBlackhole is greater than 0 for "
            "5 consecutive minutes and pages the network on-call.",
            "Transit Gateway Flow Logs are delivered to the hrl-log-archive account with 60-second aggregation.",
        ]),
        ("h1", "Procedure: Adding a New VPC Attachment"),
        ("steps", [
            "Raise a change ticket (CHG) and obtain CAB approval; route table changes also require SARB approval "
            "per HRL-ARC-001 section 11.",
            "Allocate the VPC CIDR from the correct IPAM pool (hrl-ipam-workloads for workloads).",
            "Create the attachment from the workload account using dedicated /28 TGW subnets in each AZ.",
            "In the hrl-network-hub account, accept the attachment; auto-accept is disabled by design.",
            "Associate the attachment with exactly one spoke route table (tgw-rt-prod, tgw-rt-nonprod or tgw-rt-shared).",
            "Propagate the attachment into tgw-rt-inspection only. Do not propagate into any spoke route table.",
            "Update the firewall rule groups if the new VPC requires access to on-premises or other segments.",
            "Validate the path with VPC Reachability Analyzer and record the analysis ID in the change ticket.",
        ]),
        ("h1", "Troubleshooting Quick Reference"),
        ("table", [
            ["Symptom", "Likely cause", "First check"],
            ["Spoke cannot reach on-prem", "Missing propagation in tgw-rt-inspection", "Route table propagations"],
            ["Return traffic dropped", "Appliance mode disabled", "Inspection attachment options"],
            ["Blackhole drops increasing", "Deleted attachment still referenced", "Static routes in spoke tables"],
            ["Lambda timeout to Atlas ERP", "Security group or firewall rule", "HRL-OPS-004 Procedure B"],
        ], [1.9, 2.4, 2.4]),
    ],
}

# ---------------------------------------------------------------------------
# 3. IAM Security Policies
# ---------------------------------------------------------------------------
IAM_POLICIES = {
    "filename": "IAM_Security_Policies.pdf",
    "doc_id": "HRL-SEC-003",
    "title": "IAM Security Policies",
    "subtitle": "Identity, access and guardrail standards for AWS",
    "version": "3.1",
    "date": "2026-01-26",
    "owner": "Renata Solberg, Cloud Security Lead",
    "body": [
        ("h1", "Document Control"),
        ("table", [
            ["Field", "Value"],
            ["Document ID", "HRL-SEC-003"],
            ["Version / Status", "3.1 / Approved"],
            ["Owner", "Renata Solberg, Cloud Security Lead, Information Security Office"],
            ["Approver", "Chief Information Security Officer"],
            ["Review cycle", "Every 6 months or after any SEV1 security incident"],
            ["Related documents", "HRL-ARC-001 Landing Zone; HRL-NET-002 Transit Gateway; HRL-OPS-004 Runbook"],
        ], [1.8, 4.9]),
        ("h1", "Policy Statement and Scope"),
        ("p", "This policy applies to every AWS account in the HRL AWS Organization, every human user and every "
              "workload identity. Access is granted on the principle of least privilege, is time-bound for "
              "privileged operations, and is reviewed on a fixed schedule. Violations are tracked as security "
              "findings and must be remediated within the SLAs in section 11. Exceptions follow section 12."),
        ("h1", "Identity Sources and Authentication"),
        ("p", "Human access to AWS is provided exclusively through AWS IAM Identity Center. The identity source is "
              "the corporate Keystone IdP using SAML 2.0 for authentication and SCIM for user and group "
              "provisioning. Identity Center administration is delegated to the hrl-shared-services account "
              "(290563718845). Deprovisioning must complete within 4 hours of an HR termination event."),
        ("p", "Multi-factor authentication is mandatory for all users. Phishing-resistant FIDO2 security keys "
              "are required for the HRL-PlatformAdmin and HRL-BreakGlass permission sets; push-based MFA is "
              "acceptable for other permission sets."),
        ("h1", "Permission Sets"),
        ("table", [
            ["Permission set", "Session", "Scope", "Assigned to"],
            ["HRL-ReadOnly", "8 hours", "ReadOnlyAccess", "All engineers, all accounts"],
            ["HRL-Developer", "8 hours", "PowerUser with HRL-DeveloperBoundary", "App teams, nonprod accounts"],
            ["HRL-ProdOperator", "4 hours", "Scoped operations policy", "On-call engineers, prod accounts"],
            ["HRL-PlatformAdmin", "4 hours", "AdministratorAccess", "CPE platform team only"],
            ["HRL-SecurityAuditor", "12 hours", "SecurityAudit + ViewOnlyAccess", "Security office, all accounts"],
            ["HRL-BreakGlass", "1 hour", "AdministratorAccess", "Two named directors, emergency only"],
        ], [1.6, 0.8, 2.3, 2.0]),
        ("p", "The HRL-PlatformAdmin permission set has a maximum session duration of 4 hours and is assigned "
              "only to the CPE platform team. Developers do not receive write access to production accounts; "
              "production changes are made by the deployment pipeline or by on-call engineers using "
              "HRL-ProdOperator during an active incident."),
        ("h1", "Root User and Break-Glass Access"),
        ("p", "Root user credentials for member accounts are centrally managed and root sessions are disabled "
              "using the hrl-scp-deny-root SCP. The management account root user is protected by two hardware "
              "MFA tokens stored in separate safes at the Dayton headquarters and the Columbus office."),
        ("p", "Two break-glass IAM users, hrl-breakglass-01 and hrl-breakglass-02, exist only in the "
              "hrl-management account. Their passwords are split between two custodians (dual control). Any "
              "console sign-in by a break-glass user matches the EventBridge rule hrl-breakglass-login, which "
              "notifies the SNS topic hrl-security-critical and opens a SEV1 security incident. Break-glass "
              "passwords are rotated after every use and at least every 90 days."),
        ("h1", "IAM Users and Access Keys"),
        ("p", "Long-term IAM user access keys are prohibited for humans. Workload exceptions (for example, a "
              "third-party SaaS integration that cannot assume a role) must be registered in the exception "
              "register with an ID of the form SEC-EXC-NNN. Access keys must be rotated at a maximum age of "
              "90 days. Credentials unused for 45 days are automatically disabled, and credentials unused for "
              "90 days are deleted. The IAM password policy for the remaining IAM users requires a minimum length "
              "of 16 characters and prevents reuse of the last 24 passwords."),
        ("h1", "Service Control Policies"),
        ("table", [
            ["SCP", "Attached to", "Effect"],
            ["hrl-scp-deny-regions", "Root (except Security OU)", "Deny actions outside us-east-2 and us-west-2"],
            ["hrl-scp-deny-leave-org", "Root", "Deny organizations:LeaveOrganization"],
            ["hrl-scp-deny-root", "Root", "Deny all actions by the root user in member accounts"],
            ["hrl-scp-protect-security", "Root", "Deny disabling CloudTrail, Config, GuardDuty, Security Hub"],
            ["hrl-scp-require-imdsv2", "Workloads OUs", "Deny RunInstances unless IMDSv2 is required"],
            ["hrl-scp-sandbox-guardrails", "Sandbox OU", "Deny DX, TGW, RI purchases, instances above xlarge"],
        ], [2.0, 1.8, 2.9]),
        ("p", "AWS Organizations allows a maximum of five SCPs attached directly to a single target. The "
              "Workloads/Prod OU currently uses four of its five SCP slots, so new controls should be merged "
              "into an existing SCP rather than attached separately. The region restriction SCP is shown below."),
        ("code", '{\n'
                 '  "Sid": "DenyOutsideApprovedRegions",\n'
                 '  "Effect": "Deny",\n'
                 '  "NotAction": ["iam:*", "organizations:*", "route53:*", "cloudfront:*",\n'
                 '                "support:*", "budgets:*", "sts:*"],\n'
                 '  "Resource": "*",\n'
                 '  "Condition": {"StringNotEquals": {\n'
                 '      "aws:RequestedRegion": ["us-east-2", "us-west-2"]}}\n'
                 '}'),
        ("h1", "Permission Boundaries"),
        ("p", "Developers using the HRL-Developer permission set may create IAM roles only under the path /app/ "
              "and only if the permission boundary HRL-DeveloperBoundary is attached to the new role. The "
              "boundary denies all IAM actions on roles whose names begin with hrl-platform-, denies changes to "
              "the boundary policy itself, and denies creation of IAM users and access keys."),
        ("h1", "Workload Roles"),
        ("p", "Each Lambda function must have its own execution role named using the convention "
              "hrl-lambda-<app>-exec. Execution roles must not use wildcard resources for write actions and must "
              "not be shared between functions. The role for the Order Event Processor is "
              "hrl-lambda-order-ingest-exec and grants only the permissions listed below."),
        ("table", [
            ["Action", "Resource"],
            ["sqs:ReceiveMessage, sqs:DeleteMessage, sqs:GetQueueAttributes", "Queue hrl-prod-order-events"],
            ["dynamodb:PutItem, dynamodb:UpdateItem", "Table hrl-prod-orders"],
            ["kms:Decrypt, kms:GenerateDataKey", "Key alias/hrl-prod-orders"],
            ["secretsmanager:GetSecretValue", "Secret hrl/prod/atlas-erp/api-credentials"],
            ["ec2:CreateNetworkInterface and related ENI actions", "Required for VPC-attached functions"],
        ], [3.6, 3.1]),
        ("h1", "Encryption and Key Management"),
        ("p", "Customer managed KMS keys are created per environment and per data domain. Automatic key rotation "
              "is enabled with an annual (365-day) rotation period. Key administrators and key users are "
              "separate roles: the CPE platform team administers keys but cannot use them to decrypt data, and "
              "workload roles can use keys but cannot change key policies."),
        ("h1", "Access Reviews and Findings"),
        ("p", "Privileged permission set assignments (HRL-PlatformAdmin, HRL-ProdOperator, HRL-BreakGlass) are "
              "reviewed quarterly. Standard assignments are reviewed semiannually. The organization-level IAM "
              "Access Analyzer hrl-org-access-analyzer runs in the hrl-security-tooling account and its findings "
              "must be remediated within the following SLAs."),
        ("table", [
            ["Finding severity", "Remediation SLA", "Escalation if missed"],
            ["Critical", "24 hours", "CISO"],
            ["High", "7 days", "Director of Cloud Platform Engineering"],
            ["Medium", "30 days", "Application owner manager"],
            ["Low", "90 days", "Tracked in quarterly report"],
        ], [2.0, 2.0, 2.7]),
        ("h1", "Exceptions"),
        ("p", "Exceptions to this policy require approval from the Security Architecture Review Board (SARB), "
              "must document compensating controls, and are valid for a maximum of 180 days. Expired exceptions "
              "are treated as High severity findings."),
    ],
}

# ---------------------------------------------------------------------------
# 4. Lambda Incident Runbook
# ---------------------------------------------------------------------------
LAMBDA_RUNBOOK = {
    "filename": "Lambda_Incident_Runbook.pdf",
    "doc_id": "HRL-OPS-004",
    "title": "Lambda Incident Runbook",
    "subtitle": "Order Event Processor (hrl-prod-order-ingest)",
    "version": "1.9",
    "date": "2026-04-02",
    "owner": "Kwame Asante, Site Reliability Engineering Manager",
    "body": [
        ("h1", "Document Control"),
        ("table", [
            ["Field", "Value"],
            ["Document ID", "HRL-OPS-004"],
            ["Version / Status", "1.9 / Approved"],
            ["Owner", "Kwame Asante, SRE Manager, Cloud Platform Engineering (CPE)"],
            ["Service", "Order Event Processor (OEP), AppId APP-0217"],
            ["On-call rotations", "cpe-primary (first responder), cpe-secondary (escalation)"],
            ["Related documents", "HRL-NET-002 Transit Gateway; HRL-SEC-003 IAM; SOW-HRL-2026-017"],
        ], [1.8, 4.9]),
        ("h1", "Service Overview"),
        ("p", "The Order Event Processor (OEP) ingests shipment order events from partner carriers and records "
              "them for downstream billing and tracking. OEP is classified as a Tier 1 application. Events "
              "arrive through Amazon API Gateway, are buffered in the SQS queue hrl-prod-order-events and are "
              "processed by the Lambda function hrl-prod-order-ingest. The function writes each order to the "
              "DynamoDB table hrl-prod-orders and posts confirmations to the on-premises Atlas ERP system at "
              "172.20.14.25 on TCP port 8443."),
        ("p", "The function runs in the hrl-prod-workloads account (538946102277) inside the VPC "
              "vpc-prod-orders-use2, using private subnets in us-east-2a and us-east-2b. Traffic to Atlas ERP "
              "leaves through the Transit Gateway, is inspected by AWS Network Firewall and reaches the Dayton "
              "data center over Direct Connect, as described in HRL-NET-002. The execution role is "
              "hrl-lambda-order-ingest-exec as defined in HRL-SEC-003 section 9."),
        ("h1", "Function Configuration Baseline"),
        ("table", [
            ["Setting", "Value"],
            ["Runtime / architecture", "python3.12 / arm64"],
            ["Memory / timeout", "1024 MB / 30 seconds"],
            ["Reserved concurrency", "400"],
            ["Provisioned concurrency", "50 on alias live, 07:00-21:00 ET"],
            ["Event source", "SQS hrl-prod-order-events, batch size 10, batching window 2 seconds"],
            ["Partial batch response", "ReportBatchItemFailures enabled"],
            ["Queue visibility timeout", "180 seconds (6 x function timeout)"],
            ["Redrive policy", "maxReceiveCount 5 to hrl-prod-order-events-dlq"],
            ["DLQ retention", "14 days"],
            ["Log group / retention", "/aws/lambda/hrl-prod-order-ingest / 30 days"],
            ["Deployment", "CodeDeploy, Canary10Percent5Minutes on alias live"],
        ], [2.2, 4.5]),
        ("p", "The function hrl-prod-order-ingest is configured with 1024 MB of memory, a 30 second timeout and "
              "a reserved concurrency of 400. The SQS queue visibility timeout is 180 seconds, which is six times "
              "the function timeout, and messages move to the dead-letter queue hrl-prod-order-events-dlq after "
              "a maxReceiveCount of 5."),
        ("h1", "Severity Levels and Escalation"),
        ("table", [
            ["Severity", "Trigger examples", "Acknowledge", "Updates"],
            ["SEV1", "Error rate above 25% for 5 min, or DLQ depth above 1,000", "15 minutes", "Every 30 min"],
            ["SEV2", "Error rate above 2% for 5 min, or throttles above 50 in 5 min", "30 minutes", "Every 60 min"],
            ["SEV3", "Any message in DLQ, or p99 duration above 24 s", "4 business hours", "Daily"],
        ], [0.8, 3.4, 1.3, 1.2]),
        ("p", "If the cpe-primary on-call engineer does not acknowledge a page within 10 minutes, the page "
              "escalates automatically to cpe-secondary. Every SEV1 requires a named Incident Commander, and "
              "customer-facing status updates are published by the Customer Operations desk."),
        ("h1", "CloudWatch Alarms"),
        ("table", [
            ["Alarm", "Condition", "Severity"],
            ["oep-error-rate-critical", "Errors / Invocations above 25% for 5 min", "SEV1"],
            ["oep-error-rate-high", "Errors / Invocations above 2% for 5 min", "SEV2"],
            ["oep-throttles", "Throttles sum above 50 in 5 min", "SEV2"],
            ["oep-duration-p99", "Duration p99 above 24,000 ms (80% of timeout)", "SEV3"],
            ["oep-dlq-not-empty", "DLQ ApproximateNumberOfMessagesVisible above 0", "SEV3"],
            ["oep-queue-age", "ApproximateAgeOfOldestMessage above 300 s", "SEV2"],
        ], [2.0, 3.7, 1.0]),
        ("h1", "Triage: First 10 Minutes"),
        ("steps", [
            "Acknowledge the page and join the incident bridge channel #inc-oep.",
            "Check the CloudWatch dashboard OEP-Prod-Overview for errors, throttles, duration and queue age.",
            "Check whether a deployment occurred in the last 60 minutes (CodeDeploy application hrl-oep-deploy).",
            "Search the log group with Logs Insights for the most frequent error message in the last 15 minutes.",
            "Classify the incident: throttling (Procedure A), timeouts or ERP connectivity (Procedure B), "
            "poison messages in the DLQ (Procedure C) or a bad deployment (Procedure D).",
        ]),
        ("h1", "Procedure A: Throttling"),
        ("p", "Throttling occurs when concurrent executions reach the reserved concurrency of 400. The "
              "hrl-prod-workloads account has a regional concurrency quota of 3,000. The on-call engineer may "
              "raise reserved concurrency for hrl-prod-order-ingest up to a maximum of 600 without CAB approval. "
              "Any value above 600 requires emergency CAB approval because Atlas ERP supports at most 650 "
              "concurrent connections."),
        ("code", "aws lambda put-function-concurrency \\\n"
                 "  --function-name hrl-prod-order-ingest \\\n"
                 "  --reserved-concurrent-executions 600"),
        ("h1", "Procedure B: Timeouts and ERP Connectivity"),
        ("steps", [
            "Confirm that duration is near the 30 second timeout and that logs show connection timeouts to "
            "172.20.14.25:8443.",
            "Verify that the security group sg-0e41b7c9d2a3f6058 allows egress to 172.20.14.0/24 on TCP 8443.",
            "Run VPC Reachability Analyzer from the function ENI to 172.20.14.25 on port 8443.",
            "Ask network on-call to check the tgw-rt-prod and tgw-rt-onprem route tables, the "
            "hrl-tgw-blackhole-drops alarm and Network Firewall alert logs (HRL-NET-002 sections 5 and 9).",
            "If Direct Connect is down, confirm VPN failover and expect reduced throughput.",
            "If Atlas ERP itself is degraded, reduce reserved concurrency to 100 to protect the ERP and let "
            "messages accumulate in SQS.",
        ]),
        ("h1", "Procedure C: Dead-Letter Queue Redrive"),
        ("p", "Redrive messages from hrl-prod-order-events-dlq back to the source queue only after the root cause "
              "is fixed. Use the SQS console or StartMessageMoveTask with a maximum velocity of 50 messages per "
              "second. Redriving more than 10,000 messages requires approval from the Incident Commander. "
              "Messages that fail again after redrive are exported to the bucket hrl-oep-poison-archive for "
              "manual review. DLQ messages expire after 14 days, so redrive must start within that window."),
        ("h1", "Procedure D: Bad Deployment Rollback"),
        ("p", "Deployments shift traffic on the alias live using the CodeDeploy configuration "
              "Canary10Percent5Minutes and roll back automatically if oep-error-rate-high fires during the canary. "
              "For a manual rollback, point the alias live back to the previous published version:"),
        ("code", "aws lambda update-alias --function-name hrl-prod-order-ingest \\\n"
                 "  --name live --function-version <previous-version>"),
        ("h1", "Procedure E: Regional Failover to us-west-2"),
        ("p", "Regional failover is invoked only by the Incident Commander when us-east-2 is impaired and the "
              "outage is expected to breach the Tier 1 recovery time objective of 1 hour defined in "
              "SOW-HRL-2026-017. A warm-standby copy of the function, hrl-dr-order-ingest, is deployed in "
              "us-west-2 with reserved concurrency of 200. The DynamoDB table hrl-prod-orders is a global table "
              "replicated to us-west-2."),
        ("steps", [
            "Incident Commander declares regional failover and records the decision time in the incident record.",
            "Enable the event source mapping for hrl-dr-order-ingest on the queue hrl-dr-order-events in us-west-2.",
            "Switch the Route 53 failover record orders-api.hrl.example to the us-west-2 API Gateway endpoint "
            "(health check hc-orders-api-use2 is set to 3 failures at 30-second intervals).",
            "Confirm Atlas ERP reachability from us-west-2 through the inter-region Transit Gateway peering "
            "attachment (HRL-NET-002 section 8).",
            "Monitor the dashboard OEP-DR-Overview for 30 minutes before declaring the service restored.",
        ]),
        ("h1", "Dependencies and Contacts"),
        ("table", [
            ["Dependency", "Details", "Owner / contact"],
            ["Amazon API Gateway", "REST API hrl-orders-api, throttle 2,000 rps, burst 4,000", "CPE on-call"],
            ["DynamoDB hrl-prod-orders", "On-demand capacity, PITR enabled, global table", "CPE on-call"],
            ["Atlas ERP", "172.20.14.25:8443, max 650 concurrent connections", "ERP Operations, ext. 4471"],
            ["Network path", "TGW, Network Firewall, Direct Connect", "Network on-call (cpe-network)"],
            ["Secrets", "hrl/prod/atlas-erp/api-credentials, rotated every 30 days", "Security office"],
        ], [1.7, 3.3, 1.7]),
        ("h2", "Useful Logs Insights query"),
        ("code", "fields @timestamp, @message\n"
                 "| filter @message like /ERROR|Task timed out/\n"
                 "| stats count(*) as errors by bin(1m)\n"
                 "| sort errors desc\n"
                 "| limit 20"),
        ("h1", "Post-Incident Activities"),
        ("p", "A blameless postmortem is required for every SEV1 and SEV2 incident and must be published within "
              "5 business days of resolution. Action items are tracked in the CPE backlog with an owner and a "
              "due date."),
        ("p", "Reference incident INC-2291 (SEV1, 2026-03-14): a security group change removed the egress rule "
              "to 172.20.14.0/24 on TCP 8443, causing every invocation to time out against Atlas ERP. The outage "
              "lasted 47 minutes and 18,240 messages were moved to the DLQ and later redriven. Corrective action: "
              "the security group is now managed only by Terraform and the change added AWS Config rule "
              "hrl-oep-sg-egress-check."),
    ],
}

# ---------------------------------------------------------------------------
# 5. Cloud Migration SOW
# ---------------------------------------------------------------------------
MIGRATION_SOW = {
    "filename": "Cloud_Migration_SOW.pdf",
    "doc_id": "SOW-HRL-2026-017",
    "title": "Statement of Work: Cloud Migration",
    "subtitle": "Project Meridian - Data Center Exit to AWS",
    "version": "1.0 (Executed)",
    "date": "2026-01-30",
    "owner": "HRL Program Management Office",
    "body": [
        ("h1", "Parties and Term"),
        ("p", "This Statement of Work SOW-HRL-2026-017 is entered into between Halcyon Ridge Logistics, Inc. "
              "(Client) and Cobalt Arc Consulting LLC (Provider) under Master Services Agreement "
              "MSA-HRL-2024-003 dated 2024-06-10. The SOW is effective from 2026-02-02 and ends on 2026-12-18 "
              "unless extended by a signed change order. In the event of a conflict, the Master Services "
              "Agreement takes precedence over this SOW."),
        ("table", [
            ["Role", "Client (HRL)", "Provider (Cobalt Arc)"],
            ["Executive sponsor", "Marisol Vega, VP Infrastructure", "Helene Marchetti, Managing Director"],
            ["Engagement lead", "Priya Natarajan, Program Manager", "Tomasz Lindqvist, Engagement Lead"],
            ["Technical authority", "Daniel Okafor, Principal Cloud Architect", "Ines Carvalho, Principal Architect"],
        ], [1.6, 2.6, 2.5]),
        ("h1", "Background and Objectives"),
        ("p", "HRL operates its primary data center DC-DAY1 in Dayton, Ohio under a lease that expires on "
              "2027-03-31. The objective of Project Meridian is to exit DC-DAY1 by migrating the application "
              "portfolio to AWS on the landing zone defined in HRL-ARC-001. The in-scope estate consists of 186 "
              "applications running on 1,412 virtual servers with 312 TB of storage."),
        ("bullets", [
            "Complete all application cutovers by 2026-10-30, ahead of the peak-season change freeze.",
            "Reduce infrastructure run cost by at least 22 percent compared to the FY2025 data center baseline.",
            "Meet the recovery objectives for each application tier defined in section 7.",
        ]),
        ("h1", "Scope of Services"),
        ("h2", "In scope"),
        ("bullets", [
            "Build of the landing zone per HRL-ARC-001, HRL-NET-002 and HRL-SEC-003.",
            "Discovery, wave planning, migration and cutover of 160 applications.",
            "Decommissioning support for 21 retired applications.",
            "Operational runbooks for Tier 1 applications, including HRL-OPS-004 for the Order Event Processor.",
            "Knowledge transfer to the HRL Cloud Platform Engineering team (minimum 40 hours of workshops).",
        ]),
        ("h2", "Out of scope"),
        ("bullets", [
            "The IBM-compatible mainframe HRL-MF-01 and its 5 retained applications.",
            "End-user computing, desktops and the corporate WAN beyond the Direct Connect handoff.",
            "Software license procurement and third-party SaaS subscriptions.",
            "Application code changes other than for the 12 applications designated Refactor.",
        ]),
        ("h1", "Migration Portfolio"),
        ("p", "The 186 applications have been assigned a migration strategy during the Migration Readiness "
              "Assessment. Of these, 160 applications will be migrated to AWS, 21 will be retired and 5 will be "
              "retained on premises."),
        ("table", [
            ["Strategy", "Applications", "Example"],
            ["Rehost", "98", "Warehouse management (APP-0102)"],
            ["Replatform", "41", "Carrier rating engine to Amazon RDS for PostgreSQL"],
            ["Refactor", "12", "Order Event Processor (APP-0217) to AWS Lambda"],
            ["Repurchase", "9", "HR timekeeping to SaaS"],
            ["Retire", "21", "Legacy fax gateway"],
            ["Retain", "5", "Mainframe HRL-MF-01 workloads"],
            ["Total", "186", ""],
        ], [1.6, 1.3, 3.8]),
        ("h1", "Phases and Timeline"),
        ("table", [
            ["Phase", "Dates", "Applications", "Exit criteria"],
            ["Phase 0 - Mobilize", "2026-02-02 to 2026-02-13", "-", "Plan baselined, team onboarded"],
            ["Phase 1 - Foundation", "2026-02-16 to 2026-03-27", "-", "Landing zone accepted (D2)"],
            ["Wave 1", "2026-04-06 to 2026-06-12", "44", "All Wave 1 cutovers complete"],
            ["Wave 2", "2026-06-15 to 2026-08-28", "70", "All Wave 2 cutovers complete"],
            ["Wave 3", "2026-08-31 to 2026-10-30", "46", "All Wave 3 cutovers complete"],
            ["Hypercare and Closure", "2026-11-02 to 2026-12-18", "-", "Closure report accepted (D5)"],
        ], [1.7, 1.9, 1.0, 2.1]),
        ("p", "The Order Event Processor (APP-0217) is migrated in Wave 2 using the Refactor strategy. Wave 2 "
              "runs from 2026-06-15 to 2026-08-28 and includes 70 applications. No production cutovers may occur "
              "during the HRL peak-season change freeze from 2026-11-16 to 2027-01-04."),
        ("h1", "Deliverables and Acceptance"),
        ("table", [
            ["ID", "Deliverable", "Due"],
            ["D1", "Migration Readiness Assessment and portfolio strategy", "2026-02-13"],
            ["D2", "Landing zone build and as-built documentation", "2026-03-27"],
            ["D3", "Wave plans and cutover runbooks for each wave", "Two weeks before each wave"],
            ["D4", "Tier 1 operational runbooks (including HRL-OPS-004)", "Before each Tier 1 cutover"],
            ["D5", "Closure report and knowledge transfer completion", "2026-12-18"],
        ], [0.6, 4.2, 1.9]),
        ("p", "Client will review each deliverable within an acceptance period of 10 business days. If Client "
              "does not accept or reject a deliverable within the acceptance period, the deliverable is deemed "
              "accepted. Rejections must list specific deficiencies, and Provider will resubmit within 5 "
              "business days."),
        ("h1", "Service Levels and Recovery Objectives"),
        ("p", "Cutovers are performed in the standard window from Saturday 22:00 ET to Sunday 06:00 ET. The "
              "go/no-go rollback decision point is 03:00 ET. Unplanned downtime for a Tier 1 application during "
              "cutover must not exceed 30 minutes beyond the approved window."),
        ("table", [
            ["Tier", "RTO", "RPO", "Example applications"],
            ["Tier 1", "1 hour", "15 minutes", "Order Event Processor, warehouse management"],
            ["Tier 2", "4 hours", "1 hour", "Carrier rating engine, customer portal"],
            ["Tier 3", "24 hours", "24 hours", "Reporting, batch archive"],
        ], [0.9, 1.0, 1.1, 3.7]),
        ("p", "Tier 1 applications have a recovery time objective (RTO) of 1 hour and a recovery point objective "
              "(RPO) of 15 minutes. For each missed Tier 1 cutover service level, Provider will credit 2 percent "
              "of the related milestone fee, capped at 10 percent of the total fixed fee."),
        ("h1", "Fees and Payment"),
        ("p", "The total fixed fee for this SOW is USD 2,480,000, invoiced on completion of the milestones below. "
              "Payment terms are net 45 days from invoice. Travel expenses are reimbursed at cost and capped at "
              "5 percent of the fixed fee (USD 124,000)."),
        ("table", [
            ["Milestone", "Trigger", "Percent", "Amount (USD)"],
            ["M1", "Phase 0 complete, D1 accepted", "10%", "248,000"],
            ["M2", "Landing zone accepted (D2)", "20%", "496,000"],
            ["M3", "Wave 1 complete", "20%", "496,000"],
            ["M4", "Wave 2 complete", "25%", "620,000"],
            ["M5", "Wave 3 complete", "15%", "372,000"],
            ["M6", "Closure report accepted (D5)", "10%", "248,000"],
            ["Total", "", "100%", "2,480,000"],
        ], [1.0, 3.0, 1.0, 1.7]),
        ("p", "Work requested through change orders is billed on a time-and-materials basis at the following "
              "hourly rates: Principal Architect USD 285, Senior Cloud Engineer USD 230, Project Manager "
              "USD 210 and Cloud Engineer USD 185."),
        ("h1", "Governance"),
        ("p", "A Steering Committee chaired by Marisol Vega meets monthly. Weekly status reports are delivered "
              "every Thursday. Provider must give 15 business days notice before replacing any key personnel "
              "named in section 1, and replacements require Client approval."),
        ("h1", "Assumptions and Dependencies"),
        ("bullets", [
            "HRL provides Direct Connect circuits at the Columbus and Chicago colocation sites by 2026-03-06.",
            "Application owners are available for user acceptance testing during each cutover weekend.",
            "Provider personnel use HRL-issued identities via IAM Identity Center; no IAM users are created "
            "for Provider staff (see HRL-SEC-003 section 6).",
        ]),
        ("h1", "Signatures"),
        ("table", [
            ["", "Halcyon Ridge Logistics, Inc.", "Cobalt Arc Consulting LLC"],
            ["Name", "Marisol Vega", "Helene Marchetti"],
            ["Title", "VP Infrastructure", "Managing Director"],
            ["Date", "2026-01-30", "2026-01-30"],
        ], [1.0, 2.85, 2.85]),
    ],
}

DOCUMENTS = [LANDING_ZONE, TRANSIT_GATEWAY, IAM_POLICIES, LAMBDA_RUNBOOK, MIGRATION_SOW]
