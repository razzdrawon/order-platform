# ---------------------------------------------------------------------------
# ECR — Elastic Container Registry
# ---------------------------------------------------------------------------
#
# Private Docker image registry. The CI/CD pipeline builds the image,
# tags it with the git SHA, and pushes it here. ECS pulls from here.

resource "aws_ecr_repository" "app" {
  name                 = "${var.project}/app"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true  # Automatically scan for CVEs on every push
  }

  tags = { Name = "${var.project}-ecr" }
}

# Lifecycle policy — keep only the 10 most recent images to control storage costs
resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 10 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}

output "ecr_repository_url" {
  description = "ECR repository URL — used in the CI/CD pipeline to tag and push images."
  value       = aws_ecr_repository.app.repository_url
}
