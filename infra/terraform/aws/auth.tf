# Auth seam: Cognito is provisioned as the cloud identity provider. The app
# currently issues its own HS256 JWTs (Better Auth, GG_AUTH_JWT_SECRET);
# swapping token validation to Cognito's OIDC issuer is application work
# tracked in ADR 0020 — this skeleton stands up the pool and client so the
# issuer URL exists to integrate against.

resource "aws_cognito_user_pool" "main" {
  name = "${local.name}-users"

  password_policy {
    minimum_length    = 12
    require_lowercase = true
    require_numbers   = true
    require_uppercase = true
  }

  admin_create_user_config {
    allow_admin_create_user_only = true # audit staff are provisioned, never self-signup
  }
}

resource "aws_cognito_user_pool_client" "web" {
  name         = "${local.name}-web"
  user_pool_id = aws_cognito_user_pool.main.id

  explicit_auth_flows = [
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]

  generate_secret = false
}
