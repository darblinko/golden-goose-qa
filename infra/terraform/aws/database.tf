# Postgres seam: RDS replaces the pgvector container. Migrations (alembic +
# role creation) run as gg_admin from a one-off ECS task or a bastion.

resource "aws_db_subnet_group" "main" {
  name       = "${local.name}-db"
  subnet_ids = aws_subnet.public[*].id
}

resource "aws_db_instance" "main" {
  identifier     = "${local.name}-pg"
  engine         = "postgres"
  engine_version = var.db_engine_version
  instance_class = var.db_instance_class

  db_name  = "goldengoose"
  username = "gg_admin"
  password = var.db_admin_password

  allocated_storage     = 20
  max_allocated_storage = 100
  storage_encrypted     = true

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.database.id]
  publicly_accessible    = false

  backup_retention_period = 7
  deletion_protection     = false # dev skeleton; enable for anything real
  skip_final_snapshot     = true  # dev skeleton
}
