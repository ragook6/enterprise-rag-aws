# Architecture

All resources are in one AWS account and Region (`us-west-2`) and are defined in [`infra/`](../infra). Identifiers below
are placeholders.

## Components and data flow

```mermaid
flowchart TB
  subgraph Ingestion
    D["S3 documents bucket<br/>documents/*.pdf (5 files)"] -->|StartIngestionJob| DSA["Data source A<br/>FIXED_SIZE 100 / 1%"]
    D -->|StartIngestionJob| DSB["Data source B<br/>HIERARCHICAL 1500 / 300 / 60"]
    DSA --> KBA["Knowledge Base A"]
    DSB --> KBB["Knowledge Base B"]
    KBA -->|embed chunks| T["Titan Text Embeddings V2<br/>1024-d float32"]
    KBB -->|embed child chunks| T
    KBA -->|PutVectors| IA["S3 Vectors index A<br/>cosine"]
    KBB -->|PutVectors<br/>parent text as non-filterable metadata| IB["S3 Vectors index B<br/>cosine"]
  end
  subgraph Query["Evaluation (per question, per KB)"]
    Q["question"] -->|Retrieve top-5| KBA & KBB
    KBA & KBB -->|chunks + page labels + scores| P["prompt: system rules + [S1..S5]"]
    P -->|Converse, temperature 0| N["Amazon Nova Micro<br/>us.amazon.nova-micro-v1:0"]
    N --> S["answer + citations -> lexical scoring -> JSONL"]
  end
```

## Resources (24, from `terraform plan`)

| Type | Count | Notes |
|---|---|---|
| `aws_s3_bucket` + public access block + ownership controls + SSE + bucket policy | 5 | private, SSE-S3, ACLs disabled, TLS-only |
| `aws_s3_object` | 5 | the PDFs under `documents/` |
| `aws_s3vectors_vector_bucket` | 1 | SSE-S3 |
| `aws_s3vectors_index` | 2 | 1024 dimensions, float32, cosine, `AMAZON_BEDROCK_TEXT` and `AMAZON_BEDROCK_METADATA` non-filterable |
| `aws_iam_role` + `aws_iam_role_policy` (KB service roles) | 4 | one role per Knowledge Base |
| `aws_bedrockagent_knowledge_base` | 2 | type `VECTOR`, Titan V2, storage `S3_VECTORS` |
| `aws_bedrockagent_data_source` | 2 | `DELETE` data-deletion policy; chunking is the only difference |
| `aws_iam_policy` + `aws_iam_role` + attachment (runner) | 3 | MFA-gated evaluation identity |

No hourly-billed resources (no OpenSearch, provisioned throughput, NAT gateways, KMS keys or compute).

## IAM trust and permissions

```mermaid
flowchart LR
  U["IAM user (MFA session)"] -->|sts:AssumeRole<br/>aws:MultiFactorAuthPresent = true| R["runner role"]
  R -->|bedrock:Retrieve, ingestion jobs| KB["the 2 Knowledge Bases only"]
  R -->|bedrock:InvokeModel*| IP["us.amazon.nova-micro-v1:0 profile"]
  R -->|bedrock:InvokeModel* if InferenceProfileArn = that profile| FM["amazon.nova-micro-v1:0<br/>us-east-1 / us-east-2 / us-west-2"]
  B["bedrock.amazonaws.com"] -->|AssumeRole if SourceAccount = account<br/>and SourceArn = this KB| KR["KB service role (x2)"]
  KR --> S3["s3:GetObject documents/* only"]
  KR --> TI["InvokeModel Titan V2 only"]
  KR --> VI["s3vectors:* on its own index only"]
```

## Why S3 Vectors

Pay-per-use vector storage and queries with no provisioned capacity, which suits a low-traffic experiment. Trade-offs
observed: semantic search only (no hybrid keyword search), and hierarchical parent text is stored as vector metadata,
so very large parent sizes can exceed the per-vector metadata limit.
