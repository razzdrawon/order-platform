terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Remote state in S3 — keeps tfstate out of git and enables team collaboration.
  # The bucket is created manually once (see README), then Terraform manages everything else.
  backend "s3" {
    bucket = "order-platform-tfstate"
    key    = "prod/terraform.tfstate"
    region = "us-east-1"
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

# ---------------------------------------------------------------------------
# Data sources — look up things that already exist in AWS
# ---------------------------------------------------------------------------

data "aws_caller_identity" "current" {}
data "aws_availability_zones" "available" { state = "available" }
