# ECS Fargate services: api, worker (same image, saq command), web.
# Environment wiring mirrors infra/compose/docker-compose.yml, with the four
# seams swapped: RDS for the postgres container, native S3 for SeaweedFS
# (empty endpoint/key -> task-role credentials), managed Qdrant/Neo4j
# endpoints, Cognito provisioned for auth (see auth.tf).

resource "aws_ecs_cluster" "main" {
  name = local.name
}

resource "aws_cloudwatch_log_group" "main" {
  name              = "/ecs/${local.name}"
  retention_in_days = 30
}

locals {
  api_environment = [
    { name = "GG_ENVIRONMENT", value = var.environment },
    { name = "GG_LOG_LEVEL", value = "INFO" },
    { name = "GG_PG_HOST", value = aws_db_instance.main.address },
    { name = "GG_PG_PORT", value = "5432" },
    { name = "GG_PG_USER", value = "gg_app" },
    { name = "GG_PG_DATABASE", value = "goldengoose" },
    { name = "GG_QDRANT_URL", value = var.qdrant_url },
    { name = "GG_NEO4J_URI", value = var.neo4j_uri },
    { name = "GG_NEO4J_USER", value = var.neo4j_user },
    { name = "GG_S3_ENDPOINT_URL", value = "" },
    { name = "GG_S3_ACCESS_KEY", value = "" },
    { name = "GG_S3_SECRET_KEY", value = "" },
    { name = "GG_S3_BUCKET_DOCUMENTS", value = aws_s3_bucket.main["documents"].bucket },
    { name = "GG_S3_BUCKET_ARTIFACTS", value = aws_s3_bucket.main["artifacts"].bucket },
    { name = "GG_S3_REGION", value = var.region },
    { name = "GG_REQUIRE_REAL_PROVIDERS", value = "true" },
    # The ALB routes /api/* here unstripped, so the app serves under /api.
    # Inert for the worker (no HTTP server); shared to keep one env block.
    { name = "GG_API_ROOT_PATH", value = "/api" },
  ]

  api_secrets = concat(
    [
      { name = "GG_PG_PASSWORD", valueFrom = aws_ssm_parameter.secret["db-app-password"].arn },
      { name = "GG_AUTH_JWT_SECRET", valueFrom = aws_ssm_parameter.secret["jwt-secret"].arn },
      { name = "GG_NEO4J_PASSWORD", valueFrom = aws_ssm_parameter.secret["neo4j-password"].arn },
      { name = "GG_ANTHROPIC_API_KEY", valueFrom = aws_ssm_parameter.secret["anthropic-key"].arn },
      { name = "GG_VOYAGE_API_KEY", valueFrom = aws_ssm_parameter.secret["voyage-key"].arn },
    ],
    # Injected only when a Qdrant API key was supplied (see secrets.tf).
    [for p in aws_ssm_parameter.qdrant_api_key : { name = "GG_QDRANT_API_KEY", valueFrom = p.arn }],
  )

  log_configuration = {
    logDriver = "awslogs"
    options = {
      awslogs-group         = aws_cloudwatch_log_group.main.name
      awslogs-region        = var.region
      awslogs-stream-prefix = "svc"
    }
  }
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${local.name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([{
    name             = "api"
    image            = var.api_image
    portMappings     = [{ containerPort = 8000, protocol = "tcp" }]
    environment      = local.api_environment
    secrets          = local.api_secrets
    logConfiguration = local.log_configuration
  }])
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "${local.name}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([{
    name             = "worker"
    image            = var.api_image
    command          = ["/app/.venv/bin/saq", "gg_ingestion.worker.settings"]
    environment      = local.api_environment
    secrets          = local.api_secrets
    logConfiguration = local.log_configuration
  }])
}

resource "aws_ecs_task_definition" "web" {
  family                   = "${local.name}-web"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.execution.arn

  container_definitions = jsonencode([{
    name         = "web"
    image        = var.web_image
    portMappings = [{ containerPort = 3000, protocol = "tcp" }]
    # One-origin: build the web image with --build-arg NEXT_PUBLIC_API_URL=/api
    # so the browser calls the same origin and the ALB /api/* rule reaches the
    # API. No per-environment absolute API URL needs baking in.
    logConfiguration = local.log_configuration
  }])
}

resource "aws_ecs_service" "api" {
  name            = "api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.service.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  depends_on = [aws_lb_listener_rule.api]
}

resource "aws_ecs_service" "worker" {
  name            = "worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.service.id]
    assign_public_ip = true
  }
}

resource "aws_ecs_service" "web" {
  name            = "web"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.web.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.service.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.web.arn
    container_name   = "web"
    container_port   = 3000
  }

  depends_on = [aws_lb_listener.http_forward, aws_lb_listener.https]
}
