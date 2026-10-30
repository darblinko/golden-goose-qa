# Runtime secrets live in SSM SecureString parameters and are injected into
# containers via the ECS `secrets` mechanism, never as plain environment.

locals {
  ssm_secrets = {
    db-app-password = var.db_app_password
    jwt-secret      = var.jwt_secret
    neo4j-password  = var.neo4j_password
    anthropic-key   = var.anthropic_api_key
    voyage-key      = var.voyage_api_key
    google-key      = var.google_api_key
  }
}

resource "aws_ssm_parameter" "secret" {
  # Static key set: for_each cannot range over the sensitive map itself.
  for_each = toset(["db-app-password", "jwt-secret", "neo4j-password", "anthropic-key", "voyage-key", "google-key"])

  name  = "/${local.name}/${each.key}"
  type  = "SecureString"
  value = local.ssm_secrets[each.key]
}

# Optional: Qdrant Cloud needs an API key, a self-hosted Qdrant does not.
# Created and injected only when var.qdrant_api_key is non-empty (services.tf).
resource "aws_ssm_parameter" "qdrant_api_key" {
  count = var.qdrant_api_key != "" ? 1 : 0

  name  = "/${local.name}/qdrant-api-key"
  type  = "SecureString"
  value = var.qdrant_api_key
}
