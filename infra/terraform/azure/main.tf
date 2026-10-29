locals {
  name = "${var.project}-${var.environment}"
  # Storage account names: lowercase alphanumeric, max 24 chars.
  storage_account = replace("${substr(var.project, 0, 16)}${var.environment}", "-", "")
}

resource "azurerm_resource_group" "main" {
  name     = local.name
  location = var.location
}

resource "azurerm_log_analytics_workspace" "main" {
  name                = local.name
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
}
