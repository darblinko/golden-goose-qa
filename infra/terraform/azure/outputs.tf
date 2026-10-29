output "api_fqdn" {
  value = azurerm_container_app.api.ingress[0].fqdn
}

output "web_fqdn" {
  value = azurerm_container_app.web.ingress[0].fqdn
}

output "database_fqdn" {
  value = azurerm_postgresql_flexible_server.main.fqdn
}

output "storage_account" {
  value = azurerm_storage_account.main.name
}

output "entra_client_id" {
  description = "App registration for the auth seam swap (ADR 0020)"
  value       = azuread_application.web.client_id
}
