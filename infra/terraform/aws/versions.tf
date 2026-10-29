terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # Local state by default so a single operator can stand the stack up with no
  # prerequisites. Before any shared or repeated use, move state to S3 with
  # native locking (see REMOTE_STATE.md for the one-time bootstrap) by
  # uncommenting this block and running `terraform init -migrate-state`:
  #
  # backend "s3" {
  #   bucket       = "goldengoose-tfstate-<account-id>"
  #   key          = "aws/dev/terraform.tfstate"
  #   region       = "us-east-1"
  #   encrypt      = true
  #   use_lockfile = true # S3-native state locking (Terraform >= 1.10)
  # }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      project     = var.project
      environment = var.environment
      managed_by  = "terraform"
    }
  }
}
