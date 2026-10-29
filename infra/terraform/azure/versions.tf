terraform {
  required_version = ">= 1.6"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 3.0"
    }
  }

  # Skeleton uses local state. Point this at azurerm blob before any shared use.
  # backend "azurerm" { ... }
}

provider "azurerm" {
  features {}
}

provider "azuread" {}
