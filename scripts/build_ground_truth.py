#!/usr/bin/env python3
"""
Build data/evaluation/ground_truth.json.

Each question lists one or more source passages copied verbatim from content.py.
Page numbers are NOT hand-entered: the script extracts text from each generated
PDF with pypdf and locates the page on which each passage appears. It fails if a
passage is missing or appears on more than one page.
"""
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
DOC_DIR = ROOT / "data" / "documents"
OUT = ROOT / "data" / "evaluation" / "ground_truth.json"

LZ = "AWS_Landing_Zone_Architecture.pdf"
TGW = "Transit_Gateway_Design.pdf"
IAM = "IAM_Security_Policies.pdf"
RB = "Lambda_Incident_Runbook.pdf"
SOW = "Cloud_Migration_SOW.pdf"

# (id, type, difficulty, question, answer, answer_keywords, [(document, passage), ...])
QUESTIONS = [
    # ---------------- Landing Zone ----------------
    ("Q01", "factual", "easy",
     "Which S3 bucket receives the organization CloudTrail logs, and what is the AWS account ID of the account that owns it?",
     "The organization trail hrl-org-trail delivers to the bucket hrl-org-cloudtrail-739204615882-use2 in the hrl-log-archive account, account ID 739204615882.",
     ["hrl-org-cloudtrail-739204615882-use2", "739204615882"],
     [(LZ, "The trail delivers to the bucket hrl-org-cloudtrail-739204615882-use2 in the hrl-log-archive account (739204615882).")]),
    ("Q02", "numeric", "medium",
     "How long are CloudTrail logs retained, and how are they tiered over time?",
     "Logs are protected by S3 Object Lock in compliance mode for 400 days, then transitioned to S3 Glacier Deep Archive, and expired after 2,555 days (7 years).",
     ["400", "Glacier Deep Archive", "2,555"],
     [(LZ, "The bucket uses S3 Object Lock in compliance mode with a 400-day retention period. Objects transition to S3 Glacier Deep Archive after 400 days and are expired after 2,555 days (7 years)")]),
    ("Q03", "factual", "easy",
     "Which AWS Regions is HRL allowed to use, and what enforces the restriction?",
     "Only us-east-2 (Ohio, primary) and us-west-2 (Oregon, disaster recovery). All other Regions are blocked by the SCP hrl-scp-deny-regions, with exemptions for global services.",
     ["us-east-2", "us-west-2", "hrl-scp-deny-regions"],
     [(LZ, "The primary Region is us-east-2 (Ohio)"),
      (LZ, "The disaster recovery Region is us-west-2 (Oregon). All other Regions are blocked by the SCP hrl-scp-deny-regions")]),
    ("Q04", "numeric", "easy",
     "What are the lifetime and budget limits for sandbox accounts, and what happens when the budget is exceeded?",
     "Sandbox accounts live at most 90 days with a monthly budget of USD 500. At 120 percent of budget the account is automatically moved to the Suspended OU.",
     ["90 days", "500", "120 percent", "Suspended"],
     [(LZ, "Sandbox accounts have a maximum lifetime of 90 days and a monthly budget of USD 500. When actual spend reaches 120 percent of the sandbox budget the account is automatically moved to the Suspended OU.")]),
    ("Q05", "procedural", "easy",
     "How does a team request a new AWS account and how long does vending take?",
     "By opening a pull request to the hrl-aft-account-requests repository; Account Factory for Terraform (AFT) creates the account, with a service level of 2 business days from pull request approval.",
     ["hrl-aft-account-requests", "2 business days"],
     [(LZ, "New accounts are requested by pull request to the repository hrl-aft-account-requests."),
      (LZ, "The service level for account vending is 2 business days from pull request approval.")]),
    # ---------------- Transit Gateway ----------------
    ("Q06", "factual", "easy",
     "What is the Amazon side ASN of the primary Transit Gateway and of the DR Transit Gateway?",
     "The primary Transit Gateway hrl-tgw-use2-01 uses ASN 64620; the DR Transit Gateway hrl-tgw-usw2-01 uses ASN 64621.",
     ["64620", "64621"],
     [(TGW, "The primary Transit Gateway hrl-tgw-use2-01 uses Amazon side ASN 64620 and the DR Transit Gateway hrl-tgw-usw2-01 uses Amazon side ASN 64621.")]),
    ("Q07", "conceptual", "medium",
     "Why is appliance mode enabled on the inspection VPC attachment?",
     "Appliance mode pins both directions of a flow to the same Availability Zone firewall endpoint, which is required for symmetric routing; without it stateful inspection would drop return traffic.",
     ["same Availability Zone", "symmetric"],
     [(TGW, "Appliance mode keeps both directions of a flow pinned to the same Availability Zone firewall endpoint, which is required for symmetric routing; without it, stateful inspection drops return traffic.")]),
    ("Q08", "factual", "easy",
     "Describe HRL's AWS Direct Connect connections.",
     "Two dedicated 10 Gbps connections: Colo Site A in Columbus (dxcon-fh41a7c2) and Colo Site B in Chicago (dxcon-fg92b8d3), both attached via transit VIFs to Direct Connect gateway hrl-dxgw-01 (ASN 64630).",
     ["10 Gbps", "Columbus", "Chicago", "hrl-dxgw-01"],
     [(TGW, "HRL has two dedicated 10 Gbps AWS Direct Connect connections terminating at Colo Site A in Columbus (dxcon-fh41a7c2) and Colo Site B in Chicago (dxcon-fg92b8d3). Both connections attach to the Direct Connect gateway hrl-dxgw-01 (ASN 64630)")]),
    ("Q09", "conceptual", "medium",
     "How is Direct Connect kept preferred over the backup VPN, and how fast is failover expected to be?",
     "On-premises routers prepend AS 65010 three times on prefixes advertised over the VPN. With BFD on Direct Connect, failover to the VPN completes in under 60 seconds.",
     ["prepend", "three times", "60 seconds"],
     [(TGW, "To keep Direct Connect preferred, the on-premises routers prepend AS 65010 three times on all prefixes advertised over the VPN. With BFD on Direct Connect, failover to the VPN is expected to complete in under 60 seconds.")]),
    ("Q10", "factual", "medium",
     "What static routes are configured for the inter-region Transit Gateway peering and why?",
     "Because TGW peering does not support dynamic propagation: 10.76.0.0/14 points to the peering attachment in us-east-2 and 10.64.0.0/14 points to the peering attachment in us-west-2.",
     ["10.76.0.0/14", "10.64.0.0/14", "dynamic propagation"],
     [(TGW, "Transit Gateway peering does not support dynamic propagation, so static routes are configured: 10.76.0.0/14 points to the peering attachment in us-east-2, and 10.64.0.0/14 points to the peering attachment in us-west-2.")]),
    ("Q11", "factual", "easy",
     "Which alarm detects Transit Gateway blackhole packet drops and what is its threshold?",
     "hrl-tgw-blackhole-drops fires when PacketDropCountBlackhole is greater than 0 for 5 consecutive minutes and pages the network on-call.",
     ["hrl-tgw-blackhole-drops", "greater than 0", "5 consecutive minutes"],
     [(TGW, "The CloudWatch alarm hrl-tgw-blackhole-drops fires when PacketDropCountBlackhole is greater than 0 for 5 consecutive minutes and pages the network on-call.")]),
    # ---------------- IAM ----------------
    ("Q12", "factual", "easy",
     "What is the maximum session duration for the HRL-PlatformAdmin permission set?",
     "4 hours. It is assigned only to the CPE platform team.",
     ["4 hours"],
     [(IAM, "The HRL-PlatformAdmin permission set has a maximum session duration of 4 hours and is assigned only to the CPE platform team.")]),
    ("Q13", "numeric", "easy",
     "What are the rotation and inactivity rules for IAM access keys?",
     "Keys must be rotated at a maximum age of 90 days; credentials unused for 45 days are disabled automatically and those unused for 90 days are deleted.",
     ["90 days", "45 days"],
     [(IAM, "Access keys must be rotated at a maximum age of 90 days. Credentials unused for 45 days are automatically disabled, and credentials unused for 90 days are deleted.")]),
    ("Q14", "procedural", "medium",
     "What happens when a break-glass user signs in to the console?",
     "The sign-in matches EventBridge rule hrl-breakglass-login, which notifies SNS topic hrl-security-critical and opens a SEV1 security incident. The password is rotated after every use.",
     ["hrl-breakglass-login", "hrl-security-critical", "SEV1"],
     [(IAM, "Any console sign-in by a break-glass user matches the EventBridge rule hrl-breakglass-login, which notifies the SNS topic hrl-security-critical and opens a SEV1 security incident.")]),
    ("Q15", "factual", "medium",
     "Within what time must a High severity IAM Access Analyzer finding be remediated, and which analyzer produces these findings?",
     "High findings must be remediated within 7 days (escalated to the Director of Cloud Platform Engineering if missed). Findings come from hrl-org-access-analyzer in the hrl-security-tooling account.",
     ["7 days", "hrl-org-access-analyzer"],
     [(IAM, "The organization-level IAM Access Analyzer hrl-org-access-analyzer runs in the hrl-security-tooling account"),
      (IAM, "High 7 days Director of Cloud Platform Engineering")]),
    ("Q16", "procedural", "medium",
     "Under what conditions can a developer create a new IAM role?",
     "Only under the IAM path /app/ and only if the HRL-DeveloperBoundary permission boundary is attached to the new role.",
     ["/app/", "HRL-DeveloperBoundary"],
     [(IAM, "Developers using the HRL-Developer permission set may create IAM roles only under the path /app/ and only if the permission boundary HRL-DeveloperBoundary is attached to the new role.")]),
    ("Q17", "conceptual", "hard",
     "Why should new guardrails for the Workloads/Prod OU be merged into an existing SCP?",
     "AWS Organizations allows at most five SCPs attached directly to a target and Workloads/Prod already uses four of its five slots.",
     ["five", "four"],
     [(IAM, "The Workloads/Prod OU currently uses four of its five SCP slots, so new controls should be merged into an existing SCP rather than attached separately.")]),
    # ---------------- Lambda Runbook ----------------
    ("Q18", "numeric", "easy",
     "What memory, timeout and reserved concurrency are configured for hrl-prod-order-ingest?",
     "1024 MB memory, 30 second timeout and reserved concurrency of 400.",
     ["1024 MB", "30 second", "400"],
     [(RB, "The function hrl-prod-order-ingest is configured with 1024 MB of memory, a 30 second timeout and a reserved concurrency of 400.")]),
    ("Q19", "numeric", "medium",
     "What is the SQS visibility timeout for the order events queue and after how many receives do messages go to the DLQ?",
     "180 seconds (six times the 30 s function timeout); messages move to hrl-prod-order-events-dlq after a maxReceiveCount of 5.",
     ["180 seconds", "maxReceiveCount of 5"],
     [(RB, "The SQS queue visibility timeout is 180 seconds, which is six times the function timeout, and messages move to the dead-letter queue hrl-prod-order-events-dlq after a maxReceiveCount of 5.")]),
    ("Q20", "procedural", "medium",
     "During throttling, how high can on-call raise reserved concurrency without CAB approval, and why is there a limit?",
     "Up to 600 without CAB approval. Above 600 needs emergency CAB approval because Atlas ERP supports at most 650 concurrent connections.",
     ["600", "650"],
     [(RB, "The on-call engineer may raise reserved concurrency for hrl-prod-order-ingest up to a maximum of 600 without CAB approval. Any value above 600 requires emergency CAB approval because Atlas ERP supports at most 650 concurrent connections.")]),
    ("Q21", "procedural", "medium",
     "What are the rules for redriving messages from the OEP dead-letter queue?",
     "Redrive only after the root cause is fixed, at a maximum of 50 messages per second; more than 10,000 messages requires Incident Commander approval; redrive must start within the 14-day DLQ retention.",
     ["50 messages per second", "10,000", "Incident Commander"],
     [(RB, "Use the SQS console or StartMessageMoveTask with a maximum velocity of 50 messages per second. Redriving more than 10,000 messages requires approval from the Incident Commander.")]),
    ("Q22", "factual", "medium",
     "What caused incident INC-2291 and what was its impact?",
     "A security group change removed the egress rule to 172.20.14.0/24 on TCP 8443, so every invocation timed out against Atlas ERP. The SEV1 outage lasted 47 minutes and 18,240 messages went to the DLQ.",
     ["security group", "8443", "47 minutes", "18,240"],
     [(RB, "Reference incident INC-2291 (SEV1, 2026-03-14): a security group change removed the egress rule to 172.20.14.0/24 on TCP 8443, causing every invocation to time out against Atlas ERP. The outage lasted 47 minutes and 18,240 messages were moved to the DLQ")]),
    ("Q23", "procedural", "easy",
     "What happens if the primary on-call engineer does not acknowledge an OEP page?",
     "After 10 minutes without acknowledgement the page escalates automatically to the cpe-secondary rotation.",
     ["10 minutes", "cpe-secondary"],
     [(RB, "If the cpe-primary on-call engineer does not acknowledge a page within 10 minutes, the page escalates automatically to cpe-secondary.")]),
    # ---------------- SOW ----------------
    ("Q24", "numeric", "easy",
     "What is the total fixed fee of the Project Meridian SOW and what are the payment terms?",
     "USD 2,480,000, invoiced on milestone completion, payable net 45 days.",
     ["2,480,000", "net 45"],
     [(SOW, "The total fixed fee for this SOW is USD 2,480,000, invoiced on completion of the milestones below. Payment terms are net 45 days from invoice.")]),
    ("Q25", "numeric", "medium",
     "How many applications are in scope and how do they break down between migrate, retire and retain?",
     "186 applications: 160 migrated to AWS, 21 retired and 5 retained on premises.",
     ["186", "160", "21", "5"],
     [(SOW, "The 186 applications have been assigned a migration strategy"),
      (SOW, "Of these, 160 applications will be migrated to AWS, 21 will be retired and 5 will be retained on premises.")]),
    ("Q26", "factual", "easy",
     "What is the deliverable acceptance period and what happens if the client does not respond?",
     "10 business days; if the client neither accepts nor rejects within that period the deliverable is deemed accepted.",
     ["10 business days", "deemed accepted"],
     [(SOW, "Client will review each deliverable within an acceptance period of 10 business days. If Client does not accept or reject a deliverable within the acceptance period, the deliverable is deemed accepted.")]),
    ("Q27", "factual", "easy",
     "What is the standard cutover window and the go/no-go decision point?",
     "Saturday 22:00 ET to Sunday 06:00 ET, with the go/no-go rollback decision at 03:00 ET.",
     ["22:00", "06:00", "03:00"],
     [(SOW, "Cutovers are performed in the standard window from Saturday 22:00 ET to Sunday 06:00 ET. The go/no-go rollback decision point is 03:00 ET.")]),
    ("Q28", "factual", "easy",
     "Why must Project Meridian finish before 2027-03-31, and what is the size of the estate?",
     "The DC-DAY1 Dayton data center lease expires on 2027-03-31. The estate is 186 applications on 1,412 virtual servers with 312 TB of storage.",
     ["2027-03-31", "1,412", "312 TB"],
     [(SOW, "HRL operates its primary data center DC-DAY1 in Dayton, Ohio under a lease that expires on 2027-03-31."),
      (SOW, "186 applications running on 1,412 virtual servers with 312 TB of storage.")]),
    ("Q29", "factual", "easy",
     "When is the peak-season change freeze?",
     "From 2026-11-16 to 2027-01-04; no production cutovers may occur during it.",
     ["2026-11-16", "2027-01-04"],
     [(SOW, "No production cutovers may occur during the HRL peak-season change freeze from 2026-11-16 to 2027-01-04.")]),
    # ---------------- Multi-hop (cross-document) ----------------
    ("Q30", "multi_hop", "hard",
     "What is the CIDR of the VPC that hosts the Order Event Processor Lambda, and which Transit Gateway route table is it associated with?",
     "The function runs in vpc-prod-orders-use2, which is 10.66.0.0/20 and is associated with tgw-rt-prod (whose only route is a default route to the inspection attachment).",
     ["vpc-prod-orders-use2", "10.66.0.0/20", "tgw-rt-prod"],
     [(RB, "The function runs in the hrl-prod-workloads account (538946102277) inside the VPC vpc-prod-orders-use2"),
      (TGW, "The production order-processing VPC vpc-prod-orders-use2 (10.66.0.0/20) belongs to the hrl-prod-workloads account and is associated with the route table tgw-rt-prod.")]),
    ("Q31", "multi_hop", "hard",
     "What RTO and RPO apply to the Order Event Processor, and which backup plan supports it?",
     "OEP is Tier 1, so RTO is 1 hour and RPO is 15 minutes. It uses AWS Backup plan hrl-backup-tier1 with hourly snapshots copied to a locked vault in us-west-2.",
     ["Tier 1", "1 hour", "15 minutes", "hrl-backup-tier1"],
     [(RB, "OEP is classified as a Tier 1 application."),
      (SOW, "Tier 1 applications have a recovery time objective (RTO) of 1 hour and a recovery point objective (RPO) of 15 minutes."),
      (LZ, "Tier 1 workloads use the hrl-backup-tier1 plan, which takes hourly snapshots and copies every recovery point to a vault in us-west-2")]),
    ("Q32", "multi_hop", "medium",
     "What naming convention governs Lambda execution roles, and what is the role name for the Order Event Processor?",
     "Roles follow hrl-lambda-<app>-exec, one role per function; OEP uses hrl-lambda-order-ingest-exec.",
     ["hrl-lambda-<app>-exec", "hrl-lambda-order-ingest-exec"],
     [(IAM, "Each Lambda function must have its own execution role named using the convention hrl-lambda-<app>-exec."),
      (RB, "The execution role is hrl-lambda-order-ingest-exec")]),
    ("Q33", "multi_hop", "hard",
     "In which migration wave and with which strategy is the Order Event Processor migrated, and what milestone payment is triggered when that wave completes?",
     "Wave 2 (2026-06-15 to 2026-08-28) using the Refactor strategy; completing Wave 2 triggers milestone M4, 25 percent or USD 620,000.",
     ["Wave 2", "Refactor", "620,000"],
     [(SOW, "The Order Event Processor (APP-0217) is migrated in Wave 2 using the Refactor strategy. Wave 2 runs from 2026-06-15 to 2026-08-28"),
      (SOW, "M4 Wave 2 complete 25% 620,000")]),
    ("Q34", "multi_hop", "hard",
     "During a regional failover of the Order Event Processor, how does the DR function reach Atlas ERP, and which Transit Gateway serves us-west-2?",
     "Through the inter-region Transit Gateway peering attachment (tgw-attach-03f90b17d3af0c2e9) between hrl-tgw-use2-01 and the DR Transit Gateway hrl-tgw-usw2-01 (ASN 64621), then over Direct Connect to Dayton.",
     ["peering", "hrl-tgw-usw2-01"],
     [(RB, "Confirm Atlas ERP reachability from us-west-2 through the inter-region Transit Gateway peering attachment (HRL-NET-002 section 8)."),
      (TGW, "The primary and DR Transit Gateways are connected by the peering attachment tgw-attach-03f90b17d3af0c2e9."),
      (TGW, "the DR Transit Gateway hrl-tgw-usw2-01 uses Amazon side ASN 64621")]),
    # ---------------- Unanswerable (tests refusal / hallucination) ----------------
    ("Q35", "unanswerable", "medium",
     "What is HRL's monthly AWS Enterprise Support cost?",
     "The documents do not state this. A correct RAG answer should say the information is not available in the provided documents.",
     [],
     []),
]


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def page_texts(path: Path):
    return [norm(p.extract_text() or "") for p in PdfReader(str(path)).pages]


def main():
    cache, doc_meta, errors, items = {}, [], [], []
    for pdf in sorted(DOC_DIR.glob("*.pdf")):
        cache[pdf.name] = page_texts(pdf)
        doc_meta.append({"document": pdf.name, "pages": len(cache[pdf.name]),
                         "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest()})

    for qid, qtype, diff, question, answer, keywords, sources in QUESTIONS:
        out_sources = []
        for doc, passage in sources:
            hits = [i + 1 for i, t in enumerate(cache[doc]) if norm(passage) in t]
            if len(hits) != 1:
                errors.append(f"{qid}: passage found on pages {hits} of {doc}: {passage[:70]!r}")
                continue
            out_sources.append({"document": doc, "page": hits[0], "passage": passage})
        items.append({
            "id": qid, "question": question, "answer": answer, "question_type": qtype,
            "difficulty": diff, "answer_keywords": keywords, "sources": out_sources,
        })

    if errors:
        print("Ground truth build FAILED:\n  " + "\n  ".join(errors))
        sys.exit(1)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "dataset": "hrl-enterprise-rag-eval",
        "version": "1.0",
        "generated_on": date.today().isoformat(),
        "organization": "Halcyon Ridge Logistics (fictional)",
        "notes": "Page numbers are 1-based physical PDF pages located automatically from extracted text. "
                 "answer_keywords are the facts a correct answer must contain; an empty sources list means "
                 "the question is intentionally unanswerable from the corpus.",
        "documents": doc_meta,
        "questions": items,
    }
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)} with {len(items)} questions")


if __name__ == "__main__":
    main()
