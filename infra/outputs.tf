output "documents_bucket" {
  description = "S3 bucket holding the source PDFs."
  value       = aws_s3_bucket.docs.bucket
}

output "uploaded_documents" {
  description = "Object keys uploaded to the documents bucket."
  value       = sort([for o in aws_s3_object.documents : o.key])
}

output "vector_bucket" {
  description = "S3 vector bucket name."
  value       = aws_s3vectors_vector_bucket.this.vector_bucket_name
}

output "experiments" {
  description = "Per-experiment IDs consumed by the evaluation runner (terraform output -json experiments)."
  value = {
    for k, v in var.experiments : k => {
      knowledge_base_id  = aws_bedrockagent_knowledge_base.experiment[k].id
      knowledge_base_arn = aws_bedrockagent_knowledge_base.experiment[k].arn
      data_source_id     = aws_bedrockagent_data_source.experiment[k].data_source_id
      vector_index_arn   = aws_s3vectors_index.experiment[k].index_arn
      service_role_arn   = aws_iam_role.kb[k].arn
      chunking_strategy  = v.strategy
    }
  }
}

output "kb_trust_source_arns" {
  description = "Paste into terraform.tfvars as kb_trust_source_arns to narrow each KB role's trust to its own KB."
  value       = { for k, kb in aws_bedrockagent_knowledge_base.experiment : k => kb.arn }
}

output "controlled_variables" {
  description = "Settings that are identical across experiments."
  value = {
    region                          = var.aws_region
    embedding_model_id              = var.embedding_model_id
    embedding_dimensions            = var.embedding_dimensions
    distance_metric                 = var.distance_metric
    generation_inference_profile_id = var.generation_inference_profile_id
  }
}

output "runner_role_arn" {
  description = "Role the evaluation runner assumes (aws sts assume-role / AWS_PROFILE with role_arn)."
  value       = try(aws_iam_role.runner[0].arn, null)
}

output "runner_policy_arn" {
  description = "Least-privilege policy attached to the runner role."
  value       = try(aws_iam_policy.runner[0].arn, null)
}
