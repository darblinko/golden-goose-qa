# Object store seam: Blob with hierarchical namespace off, reached through
# the S3ObjectStore adapter. Blob has no native S3 API, so services either
# point GG_S3_ENDPOINT_URL at an S3 gateway in front of Blob or the
# ObjectStore seam gets a native azure-blob implementation (ADR 0020 records
# this as the one seam needing code for Azure).

resource "azurerm_storage_account" "main" {
  name                     = local.storage_account
  resource_group_name      = azurerm_resource_group.main.name
  location                 = azurerm_resource_group.main.location
  account_tier             = "Standard"
  account_replication_type = "LRS"

  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false
}

resource "azurerm_storage_container" "main" {
  for_each = toset(["gg-documents", "gg-artifacts", "gg-backups"])

  name                  = each.key
  storage_account_id    = azurerm_storage_account.main.id
  container_access_type = "private"
}
