# Postgres seam: Flexible Server replaces the pgvector container. Migrations
# (alembic + role creation) run as gg_admin from a one-off job or a bastion.

resource "azurerm_postgresql_flexible_server" "main" {
  name                = "${local.name}-pg"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location

  version                = "17" # bump when Flexible Server offers 18 in-region
  administrator_login    = "gg_admin"
  administrator_password = var.db_admin_password

  sku_name   = "B_Standard_B1ms"
  storage_mb = 32768

  backup_retention_days = 7
}

resource "azurerm_postgresql_flexible_server_database" "main" {
  name      = "goldengoose"
  server_id = azurerm_postgresql_flexible_server.main.id
}

# Skeleton allows Azure-internal traffic; a production layout uses VNet
# integration + private DNS instead of a service firewall rule.
resource "azurerm_postgresql_flexible_server_firewall_rule" "azure_services" {
  name             = "allow-azure-services"
  server_id        = azurerm_postgresql_flexible_server.main.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}
