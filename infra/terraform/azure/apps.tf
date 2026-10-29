# Container Apps: api, worker (same image, saq command), web. Environment
# wiring mirrors infra/compose/docker-compose.yml with the seams swapped.

resource "azurerm_container_app_environment" "main" {
  name                       = local.name
  location                   = azurerm_resource_group.main.location
  resource_group_name        = azurerm_resource_group.main.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
}

locals {
  api_env = [
    { name = "GG_ENVIRONMENT", value = var.environment },
    { name = "GG_LOG_LEVEL", value = "INFO" },
    { name = "GG_PG_HOST", value = azurerm_postgresql_flexible_server.main.fqdn },
    { name = "GG_PG_PORT", value = "5432" },
    { name = "GG_PG_USER", value = "gg_app" },
    { name = "GG_PG_DATABASE", value = "goldengoose" },
    { name = "GG_QDRANT_URL", value = var.qdrant_url },
    { name = "GG_NEO4J_URI", value = var.neo4j_uri },
    { name = "GG_NEO4J_USER", value = var.neo4j_user },
    { name = "GG_S3_BUCKET_DOCUMENTS", value = "gg-documents" },
    { name = "GG_S3_BUCKET_ARTIFACTS", value = "gg-artifacts" },
    { name = "GG_REQUIRE_REAL_PROVIDERS", value = "true" },
  ]

  api_secrets = {
    pg-password    = var.db_app_password
    jwt-secret     = var.jwt_secret
    neo4j-password = var.neo4j_password
    anthropic-key  = var.anthropic_api_key
    voyage-key     = var.voyage_api_key
  }

  api_secret_env = [
    { name = "GG_PG_PASSWORD", secret_name = "pg-password" },
    { name = "GG_AUTH_JWT_SECRET", secret_name = "jwt-secret" },
    { name = "GG_NEO4J_PASSWORD", secret_name = "neo4j-password" },
    { name = "GG_ANTHROPIC_API_KEY", secret_name = "anthropic-key" },
    { name = "GG_VOYAGE_API_KEY", secret_name = "voyage-key" },
  ]
}

resource "azurerm_container_app" "api" {
  name                         = "${local.name}-api"
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = azurerm_resource_group.main.name
  revision_mode                = "Single"

  template {
    min_replicas = 1
    max_replicas = 2

    container {
      name   = "api"
      image  = var.api_image
      cpu    = 0.5
      memory = "1Gi"

      dynamic "env" {
        for_each = local.api_env
        content {
          name  = env.value.name
          value = env.value.value
        }
      }

      dynamic "env" {
        for_each = local.api_secret_env
        content {
          name        = env.value.name
          secret_name = env.value.secret_name
        }
      }
    }
  }

  dynamic "secret" {
    for_each = toset(keys(local.api_secrets))
    content {
      name  = secret.key
      value = local.api_secrets[secret.key]
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8000

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }
}

resource "azurerm_container_app" "worker" {
  name                         = "${local.name}-worker"
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = azurerm_resource_group.main.name
  revision_mode                = "Single"

  template {
    min_replicas = 1
    max_replicas = 1

    container {
      name    = "worker"
      image   = var.api_image
      command = ["/app/.venv/bin/saq", "gg_ingestion.worker.settings"]
      cpu     = 0.5
      memory  = "1Gi"

      dynamic "env" {
        for_each = local.api_env
        content {
          name  = env.value.name
          value = env.value.value
        }
      }

      dynamic "env" {
        for_each = local.api_secret_env
        content {
          name        = env.value.name
          secret_name = env.value.secret_name
        }
      }
    }
  }

  dynamic "secret" {
    for_each = toset(keys(local.api_secrets))
    content {
      name  = secret.key
      value = local.api_secrets[secret.key]
    }
  }
}

resource "azurerm_container_app" "web" {
  name                         = "${local.name}-web"
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = azurerm_resource_group.main.name
  revision_mode                = "Single"

  template {
    min_replicas = 1
    max_replicas = 2

    container {
      # NEXT_PUBLIC_API_URL is baked at image build time (Dockerfile.web ARG);
      # build the web image with the api app FQDN for this environment.
      name   = "web"
      image  = var.web_image
      cpu    = 0.25
      memory = "0.5Gi"
    }
  }

  ingress {
    external_enabled = true
    target_port      = 3000

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }
}
