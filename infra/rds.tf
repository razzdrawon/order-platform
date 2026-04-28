# ---------------------------------------------------------------------------
# RDS — PostgreSQL managed database
# ---------------------------------------------------------------------------

# Security group — only ECS tasks can connect to the DB (port 5432)
resource "aws_security_group" "rds" {
  name        = "${var.project}-rds-sg"
  description = "Allow PostgreSQL access from ECS tasks only"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_tasks.id]
  }

  tags = { Name = "${var.project}-rds-sg" }
}

# Subnet group — RDS must be placed in at least 2 AZs
resource "aws_db_subnet_group" "main" {
  name       = "${var.project}-db-subnet-group"
  subnet_ids = aws_subnet.private[*].id
  tags       = { Name = "${var.project}-db-subnet-group" }
}

resource "aws_db_instance" "postgres" {
  identifier        = "${var.project}-postgres"
  engine            = "postgres"
  engine_version    = "16"
  instance_class    = "db.t3.micro"  # Free tier eligible
  allocated_storage = 20
  storage_type      = "gp2"

  db_name  = "order_platform"
  username = var.db_username
  password = var.db_password

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]

  skip_final_snapshot     = true   # Set to false in real production
  deletion_protection     = false  # Set to true in real production
  backup_retention_period = 7      # Keep 7 days of automated backups
  multi_az                = false  # Set to true for HA in production

  tags = { Name = "${var.project}-postgres" }
}

output "db_endpoint" {
  description = "RDS endpoint — used in DATABASE_URL environment variable."
  value       = aws_db_instance.postgres.endpoint
  sensitive   = true
}
