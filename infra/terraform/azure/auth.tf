# Auth seam: an Entra ID app registration is the cloud identity provider.
# As on AWS, the app currently issues its own HS256 JWTs; swapping token
# validation to the Entra OIDC issuer is application work tracked in ADR 0020.

resource "azuread_application" "web" {
  display_name = "${local.name}-web"

  web {
    redirect_uris = ["https://localhost/auth/callback"] # replace with the app FQDN

    implicit_grant {
      id_token_issuance_enabled = true
    }
  }
}

resource "azuread_service_principal" "web" {
  client_id = azuread_application.web.client_id
}
