variable "aws_region" {
  description = "AWS region where all resources will be created."
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Project name — used as a prefix for all resource names."
  type        = string
  default     = "order-platform"
}

variable "environment" {
  description = "Deployment environment (prod, staging)."
  type        = string
  default     = "prod"
}

variable "db_username" {
  description = "PostgreSQL master username."
  type        = string
  default     = "order_user"
}

variable "db_password" {
  description = "PostgreSQL master password. Set via TF_VAR_db_password env var — never hardcode."
  type        = string
  sensitive   = true
}

variable "app_image_tag" {
  description = "Docker image tag to deploy. Set by the CI/CD pipeline."
  type        = string
  default     = "latest"
}
