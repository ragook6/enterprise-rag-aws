###############################################################################
# HRL Enterprise RAG lab - Bedrock Knowledge Bases on Amazon S3 Vectors
#
#   S3 (PDFs) --ingestion--> Bedrock KB (chunk + embed with Titan V2) --> S3 Vectors index
#   Two KBs share the same documents, embedding model and index settings; only the
#   chunking strategy differs (see var.experiments).
###############################################################################

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
  region     = var.aws_region

  docs_bucket_name   = "${var.project_name}-docs-${local.account_id}-${local.region}"
  vector_bucket_name = "${var.project_name}-vectors-${local.account_id}"
  docs_bucket_arn    = "arn:${local.partition}:s3:::${local.docs_bucket_name}"
  docs_prefix        = "documents/"

  embedding_model_arn = "arn:${local.partition}:bedrock:${local.region}::foundation-model/${var.embedding_model_id}"

  # Bedrock writes the chunk text and its own bookkeeping into these two metadata keys.
  # They must be non-filterable, otherwise they count against the small (2 KB)
  # filterable-metadata limit and ingestion fails.
  bedrock_non_filterable_keys = ["AMAZON_BEDROCK_TEXT", "AMAZON_BEDROCK_METADATA"]

  pdf_files = fileset(var.documents_dir, "*.pdf")

  # Index names/ARNs are deterministic, so IAM policies are fully known at plan time
  # and can be validated (IAM Access Analyzer) before anything is created.
  index_names = { for k, _ in var.experiments : k => "${k}-titanv2-${var.embedding_dimensions}" }
  index_arns = {
    for k, name in local.index_names :
    k => "arn:${local.partition}:s3vectors:${local.region}:${local.account_id}:bucket/${local.vector_bucket_name}/index/${name}"
  }
}

# =============================================================================
# 1. Source documents bucket (the Knowledge Base data source)
# =============================================================================
resource "aws_s3_bucket" "docs" {
  bucket = local.docs_bucket_name
  # Lab setting: lets `terraform destroy` empty and remove the bucket in one step.
  # In production you would leave this false.
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "docs" {
  bucket                  = aws_s3_bucket.docs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "docs" {
  bucket = aws_s3_bucket.docs.id
  rule {
    object_ownership = "BucketOwnerEnforced" # disables ACLs entirely
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "docs" {
  bucket = aws_s3_bucket.docs.id
  rule {
    # SSE-S3: encrypted at rest with no per-key monthly charge. A customer managed
    # KMS key would add ~USD 1/month that keeps billing after the experiment.
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

data "aws_iam_policy_document" "docs_bucket" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      local.docs_bucket_arn,
      "${local.docs_bucket_arn}/*",
    ]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "docs" {
  bucket     = aws_s3_bucket.docs.id
  policy     = data.aws_iam_policy_document.docs_bucket.json
  depends_on = [aws_s3_bucket_public_access_block.docs]
}

# Upload the five PDFs. source_hash re-uploads a file whenever it changes locally.
resource "aws_s3_object" "documents" {
  for_each = local.pdf_files

  bucket       = aws_s3_bucket.docs.id
  key          = "${local.docs_prefix}${each.value}"
  source       = "${var.documents_dir}/${each.value}"
  source_hash  = filemd5("${var.documents_dir}/${each.value}")
  content_type = "application/pdf"

  depends_on = [aws_s3_bucket_server_side_encryption_configuration.docs]
}

# =============================================================================
# 2. Vector store: one S3 vector bucket, one index per experiment
#    (AWS recommends a separate vector store per Knowledge Base.)
# =============================================================================
resource "aws_s3vectors_vector_bucket" "this" {
  vector_bucket_name = local.vector_bucket_name
  force_destroy      = true # lab setting: destroy removes indexes and vectors

  encryption_configuration {
    sse_type = "AES256" # SSE-S3; cannot be changed after creation
  }
}

resource "aws_s3vectors_index" "experiment" {
  for_each = var.experiments

  vector_bucket_name = aws_s3vectors_vector_bucket.this.vector_bucket_name
  index_name         = local.index_names[each.key]

  # Controlled variables: identical for every experiment.
  data_type       = "float32" # S3 Vectors supports float32 only
  dimension       = var.embedding_dimensions
  distance_metric = var.distance_metric

  metadata_configuration {
    non_filterable_metadata_keys = local.bedrock_non_filterable_keys
  }
}

# =============================================================================
# 3. Least-privilege service role - one per Knowledge Base
#    Each role can read only the documents prefix, invoke only the embedding
#    model, and write only to its own vector index.
# =============================================================================
# One trust policy per arm. Phase 1 (first apply): the KB does not exist yet, so the
# source ARN is limited to knowledge-base/* in this account and Region. Phase 2: put the
# KB ARNs from `terraform output` into var.kb_trust_source_arns and apply again; each role
# is then assumable only by its own Knowledge Base (an in-place trust policy update).
data "aws_iam_policy_document" "kb_trust" {
  for_each = var.experiments

  statement {
    sid     = "BedrockKnowledgeBaseAssume"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["bedrock.amazonaws.com"]
    }
    # Confused-deputy protection.
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
    condition {
      test     = contains(keys(var.kb_trust_source_arns), each.key) ? "ArnEquals" : "ArnLike"
      variable = "aws:SourceArn"
      values = [lookup(
        var.kb_trust_source_arns, each.key,
        "arn:${local.partition}:bedrock:${local.region}:${local.account_id}:knowledge-base/*"
      )]
    }
  }
}

resource "aws_iam_role" "kb" {
  for_each = var.experiments

  name                 = "${var.project_name}-kb-${each.key}"
  description          = "Service role for Bedrock Knowledge Base ${var.project_name}-${each.key}"
  assume_role_policy   = data.aws_iam_policy_document.kb_trust[each.key].json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "kb_permissions" {
  for_each = var.experiments

  statement {
    sid       = "InvokeEmbeddingModelOnly"
    effect    = "Allow"
    actions   = ["bedrock:InvokeModel"]
    resources = [local.embedding_model_arn]
  }

  statement {
    sid       = "ListDocumentsBucket"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [local.docs_bucket_arn]
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceAccount"
      values   = [local.account_id]
    }
  }

  statement {
    sid       = "ReadDocumentsPrefixOnly"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${local.docs_bucket_arn}/${local.docs_prefix}*"]
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceAccount"
      values   = [local.account_id]
    }
  }

  statement {
    sid    = "ReadWriteOwnVectorIndexOnly"
    effect = "Allow"
    actions = [
      "s3vectors:PutVectors",
      "s3vectors:GetVectors",
      "s3vectors:DeleteVectors",
      "s3vectors:QueryVectors",
      "s3vectors:GetIndex",
    ]
    resources = [local.index_arns[each.key]]
  }
}

resource "aws_iam_role_policy" "kb" {
  for_each = var.experiments

  name   = "kb-least-privilege"
  role   = aws_iam_role.kb[each.key].id
  policy = data.aws_iam_policy_document.kb_permissions[each.key].json
}

# =============================================================================
# 4. Knowledge Bases (identical except for the vector index they write to)
# =============================================================================
resource "aws_bedrockagent_knowledge_base" "experiment" {
  for_each = var.experiments

  name        = "${var.project_name}-${each.key}"
  description = each.value.description
  role_arn    = aws_iam_role.kb[each.key].arn

  knowledge_base_configuration {
    type = "VECTOR"
    vector_knowledge_base_configuration {
      embedding_model_arn = local.embedding_model_arn
      embedding_model_configuration {
        bedrock_embedding_model_configuration {
          dimensions          = var.embedding_dimensions
          embedding_data_type = "FLOAT32"
        }
      }
    }
  }

  storage_configuration {
    type = "S3_VECTORS"
    s3_vectors_configuration {
      index_arn = aws_s3vectors_index.experiment[each.key].index_arn
    }
  }

  # The role's policy must exist before Bedrock validates access to the index.
  depends_on = [aws_iam_role_policy.kb]
}

# =============================================================================
# 5. Data sources - the ONLY place the experiments differ (chunking strategy)
# =============================================================================
resource "aws_bedrockagent_data_source" "experiment" {
  for_each = var.experiments

  name              = "${each.key}-s3-documents"
  knowledge_base_id = aws_bedrockagent_knowledge_base.experiment[each.key].id
  # DELETE: removing the data source also deletes its vectors (clean teardown).
  data_deletion_policy = "DELETE"

  data_source_configuration {
    type = "S3"
    s3_configuration {
      bucket_arn         = aws_s3_bucket.docs.arn
      inclusion_prefixes = [local.docs_prefix]
    }
  }

  # Parsing is left at the default (text extraction) for both experiments, so
  # parsing cannot explain any difference in results.
  vector_ingestion_configuration {
    chunking_configuration {
      chunking_strategy = each.value.strategy

      dynamic "fixed_size_chunking_configuration" {
        for_each = each.value.strategy == "FIXED_SIZE" ? [each.value.fixed_size] : []
        content {
          max_tokens         = fixed_size_chunking_configuration.value.max_tokens
          overlap_percentage = fixed_size_chunking_configuration.value.overlap_percentage
        }
      }

      dynamic "hierarchical_chunking_configuration" {
        for_each = each.value.strategy == "HIERARCHICAL" ? [each.value.hierarchical] : []
        content {
          # First level_configuration = parent, second = child.
          level_configuration {
            max_tokens = hierarchical_chunking_configuration.value.parent_max_tokens
          }
          level_configuration {
            max_tokens = hierarchical_chunking_configuration.value.child_max_tokens
          }
          overlap_tokens = hierarchical_chunking_configuration.value.overlap_tokens
        }
      }

      dynamic "semantic_chunking_configuration" {
        for_each = each.value.strategy == "SEMANTIC" ? [each.value.semantic] : []
        content {
          max_token                       = semantic_chunking_configuration.value.max_tokens
          buffer_size                     = semantic_chunking_configuration.value.buffer_size
          breakpoint_percentile_threshold = semantic_chunking_configuration.value.breakpoint_percentile_threshold
        }
      }
    }
  }
}

# =============================================================================
# 6. Evaluation runner: least-privilege policy + a role that carries it.
#    The evaluation runs as this role (sts:AssumeRole), not as an admin user.
# =============================================================================

# Read-only lookup at plan time: which Regions/models the inference profile routes to.
data "aws_bedrock_inference_profile" "generation" {
  inference_profile_id = var.generation_inference_profile_id
}

locals {
  kb_arns                = [for kb in aws_bedrockagent_knowledge_base.experiment : kb.arn]
  generation_profile_arn = data.aws_bedrock_inference_profile.generation.inference_profile_arn
  generation_model_arns  = [for m in data.aws_bedrock_inference_profile.generation.models : m.model_arn]

  runner_trusted_principals = length(var.runner_trusted_principal_arns) > 0 ? var.runner_trusted_principal_arns : [data.aws_caller_identity.current.arn]
}

data "aws_iam_policy_document" "runner" {
  statement {
    sid       = "RetrieveFromExperimentKBsOnly"
    effect    = "Allow"
    actions   = ["bedrock:Retrieve"]
    resources = local.kb_arns
  }

  statement {
    sid    = "SyncExperimentKBsOnly"
    effect = "Allow"
    actions = [
      "bedrock:StartIngestionJob",
      "bedrock:GetIngestionJob",
      "bedrock:ListIngestionJobs",
      "bedrock:GetKnowledgeBase",
      "bedrock:GetDataSource",
    ]
    resources = local.kb_arns
  }

  # Generation model (Amazon Nova Micro via the US cross-Region inference profile), called
  # with the bedrock-runtime Converse/InvokeModel API. Converse is authorized as InvokeModel.
  # 1) the inference profile itself:
  statement {
    sid    = "InvokeGenerationModelViaInferenceProfile"
    effect = "Allow"
    actions = [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream",
    ]
    resources = [local.generation_profile_arn]
  }

  # 2) the Regional foundation models the profile routes to (read from the profile at plan
  #    time), allowed ONLY when the request arrives through that profile.
  statement {
    sid    = "InvokeUnderlyingModelOnlyViaInferenceProfile"
    effect = "Allow"
    actions = [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream",
    ]
    resources = local.generation_model_arns
    condition {
      test     = "StringEquals"
      variable = "bedrock:InferenceProfileArn"
      values   = [local.generation_profile_arn]
    }
  }

  # Removed after Gate 3 evidence:
  #  - bedrock-mantle:CreateInference (Claude via the Mantle endpoint; not used by Nova Micro)
  #  - bedrock:InvokeModel on Titan Embeddings V2 (Retrieve succeeded without it; Bedrock
  #    embeds the query with the KB service role)
}

resource "aws_iam_policy" "runner" {
  count = var.create_runner_role ? 1 : 0

  name        = "${var.project_name}-experiment-runner"
  description = "Least-privilege access for the chunking-experiment evaluation runner"
  policy      = data.aws_iam_policy_document.runner.json
}

data "aws_iam_policy_document" "runner_trust" {
  statement {
    sid     = "AllowNamedPrincipalsOnly"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "AWS"
      identifiers = local.runner_trusted_principals
    }
    # Credentials used to assume this role must have been MFA-authenticated,
    # so a leaked long-lived access key alone cannot reach the runner permissions.
    dynamic "condition" {
      for_each = var.runner_require_mfa ? [1] : []
      content {
        test     = "Bool"
        variable = "aws:MultiFactorAuthPresent"
        values   = ["true"]
      }
    }
  }
}

resource "aws_iam_role" "runner" {
  count = var.create_runner_role ? 1 : 0

  name                 = "${var.project_name}-experiment-runner"
  description          = "Assumed by the evaluation runner; carries only ${var.project_name}-experiment-runner"
  assume_role_policy   = data.aws_iam_policy_document.runner_trust.json
  max_session_duration = 3600
}

resource "aws_iam_role_policy_attachment" "runner" {
  count = var.create_runner_role ? 1 : 0

  role       = aws_iam_role.runner[0].name
  policy_arn = aws_iam_policy.runner[0].arn
}

# =============================================================================
# 7. Optional cost guardrail
# =============================================================================
resource "aws_budgets_budget" "lab" {
  count = var.budget_alert_email == null ? 0 : 1

  name         = "${var.project_name}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.budget_limit_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  # Requires the "Project" cost allocation tag to be activated in Billing.
  cost_filter {
    name   = "TagKeyValue"
    values = ["user:Project$${var.project_name}"]
  }

  dynamic "notification" {
    for_each = [80, 100]
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = [var.budget_alert_email]
    }
  }
}
