# ---------------------------------------------------------------------------
# ElastiCache — Redis managed cluster
# ---------------------------------------------------------------------------

resource "aws_security_group" "redis" {
  name        = "${var.project}-redis-sg"
  description = "Allow Redis access from ECS tasks only"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_tasks.id]
  }

  tags = { Name = "${var.project}-redis-sg" }
}

resource "aws_elasticache_subnet_group" "main" {
  name       = "${var.project}-redis-subnet-group"
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_elasticache_cluster" "redis" {
  cluster_id           = "${var.project}-redis"
  engine               = "redis"
  node_type            = "cache.t3.micro"
  num_cache_nodes      = 1
  parameter_group_name = "default.redis7"
  engine_version       = "7.0"
  port                 = 6379

  subnet_group_name  = aws_elasticache_subnet_group.main.name
  security_group_ids = [aws_security_group.redis.id]

  tags = { Name = "${var.project}-redis" }
}

output "redis_endpoint" {
  description = "Redis endpoint — used in CELERY_BROKER_URL environment variable."
  value       = "${aws_elasticache_cluster.redis.cache_nodes[0].address}:6379"
  sensitive   = true
}
