variable "aws_region" {
  description = "Region for all resources. Must offer Bedrock Knowledge Bases, Titan Embeddings V2 and S3 Vectors."
  type        = string
  default     = "us-west-2"
}

variable "project_name" {
  description = "Prefix for resource names and the Project tag. Lowercase letters, digits and hyphens."
  type        = string
  default     = "hrl-rag"

  validation {
    condition     = can(regex("^[a-z0-9-]{3,20}$", var.project_name))
    error_message = "project_name must be 3-20 chars of lowercase letters, digits or hyphens."
  }
}

variable "documents_dir" {
  description = "Local folder containing the PDFs to upload as the Knowledge Base data source."
  type        = string
  default     = "../data/documents"
}

# ---------------------------------------------------------------------------
# Controlled variables: identical for both experiments. Changing any of these
# changes BOTH Knowledge Bases, which keeps the comparison fair.
# ---------------------------------------------------------------------------
variable "embedding_model_id" {
  description = "Bedrock embedding model used by both Knowledge Bases."
  type        = string
  default     = "amazon.titan-embed-text-v2:0"
}

variable "embedding_dimensions" {
  description = "Embedding vector size. Titan Text Embeddings V2 supports 256, 512 or 1024."
  type        = number
  default     = 1024

  validation {
    condition     = contains([256, 512, 1024], var.embedding_dimensions)
    error_message = "Titan Text Embeddings V2 supports 256, 512 or 1024 dimensions."
  }
}

variable "distance_metric" {
  description = "Vector similarity metric for both S3 Vectors indexes (cosine or euclidean)."
  type        = string
  default     = "cosine"
}

variable "generation_inference_profile_id" {
  description = <<-EOT
    US cross-Region inference profile used for answer generation in BOTH experiments
    (Amazon Nova Micro). The "us." profile keeps inference in us-east-1/us-east-2/us-west-2.
    The runner IAM policy allows invoking this model ONLY through this profile.
  EOT
  type        = string
  default     = "us.amazon.nova-micro-v1:0"

  validation {
    condition     = can(regex("^us\\.(amazon|anthropic)\\.[a-z0-9.-]+(:[0-9]+)?$", var.generation_inference_profile_id))
    error_message = "Use a US (us.) Amazon or Anthropic inference profile ID, e.g. us.amazon.nova-micro-v1:0."
  }
}

# ---------------------------------------------------------------------------
# Independent variable: the chunking strategy. One Knowledge Base per entry.
# ---------------------------------------------------------------------------
variable "experiments" {
  description = "Chunking configurations to compare. Each key becomes its own index, role, KB and data source."
  type = map(object({
    description = string
    strategy    = string # FIXED_SIZE | HIERARCHICAL | SEMANTIC
    fixed_size = optional(object({
      max_tokens         = number
      overlap_percentage = number
    }))
    hierarchical = optional(object({
      parent_max_tokens = number
      child_max_tokens  = number
      overlap_tokens    = number
    }))
    semantic = optional(object({
      max_tokens                      = number
      buffer_size                     = number
      breakpoint_percentile_threshold = number
    }))
  }))

  default = {
    # Experiment A - deliberately weak baseline.
    # The API minimum for overlap is 1%, so 1% (~1 token) is the closest to "no overlap".
    baseline-fixed100 = {
      description = "Baseline: fixed-size 100-token chunks, effectively no overlap (API minimum 1%)."
      strategy    = "FIXED_SIZE"
      fixed_size  = { max_tokens = 100, overlap_percentage = 1 }
    }

    # Experiment B - improved strategy.
    # Child chunks (300 tokens) are embedded and matched precisely; the parent chunk
    # (1500 tokens) that contains the match is returned as context, so tables,
    # procedures and cross-references are not cut in half. These are the AWS defaults
    # and keep the parent text well inside the S3 Vectors per-vector metadata limit.
    improved-hierarchical = {
      description  = "Improved: hierarchical chunking, parent 1500 / child 300 tokens, 60-token overlap."
      strategy     = "HIERARCHICAL"
      hierarchical = { parent_max_tokens = 1500, child_max_tokens = 300, overlap_tokens = 60 }
    }
  }

  validation {
    condition     = alltrue([for e in values(var.experiments) : contains(["FIXED_SIZE", "HIERARCHICAL", "SEMANTIC"], e.strategy)])
    error_message = "strategy must be FIXED_SIZE, HIERARCHICAL or SEMANTIC."
  }
}

variable "create_runner_role" {
  description = <<-EOT
    Create the least-privilege evaluation-runner policy AND a role that carries it, so the
    evaluation runs with only these permissions (via sts:AssumeRole) instead of AdministratorAccess.
  EOT
  type        = bool
  default     = true
}

variable "runner_require_mfa" {
  description = "Require MFA-authenticated credentials (aws:MultiFactorAuthPresent) to assume the runner role."
  type        = bool
  default     = true
}

variable "kb_trust_source_arns" {
  description = <<-EOT
    Phase-2 hardening: map of experiment key -> Knowledge Base ARN. When set, that KB's
    service role trusts ONLY that exact KB (ArnEquals) instead of knowledge-base/*.
    Fill from `terraform output -json experiments` after the first apply.
  EOT
  type        = map(string)
  default     = {}

  validation {
    condition     = alltrue([for arn in values(var.kb_trust_source_arns) : can(regex("^arn:aws[a-z-]*:bedrock:[a-z0-9-]+:[0-9]{12}:knowledge-base/[A-Z0-9]{10}$", arn))])
    error_message = "Each value must be a full Knowledge Base ARN, e.g. arn:aws:bedrock:us-west-2:123456789012:knowledge-base/ABCDE12345."
  }
}

variable "runner_trusted_principal_arns" {
  description = "Principals allowed to assume the runner role. Empty = the identity running Terraform."
  type        = list(string)
  default     = []
}

variable "budget_alert_email" {
  description = "If set, creates a USD monthly budget for resources tagged Project=<project_name> and emails at 80%/100%."
  type        = string
  default     = null
}

variable "budget_limit_usd" {
  description = "Monthly budget limit in USD (used only when budget_alert_email is set)."
  type        = number
  default     = 10
}
