terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source = "hashicorp/aws"
      # 6.x is required for aws_s3vectors_* resources and S3_VECTORS storage on Knowledge Bases.
      version = "~> 6.73"
    }
  }
}

provider "aws" {
  region = var.aws_region

  # Every taggable resource gets these tags, so the whole lab can be found in
  # Cost Explorer / Resource Groups and verified as gone after cleanup.
  default_tags {
    tags = {
      Project     = var.project_name
      Environment = "lab"
      ManagedBy   = "terraform"
      Purpose     = "rag-chunking-experiment"
    }
  }
}
