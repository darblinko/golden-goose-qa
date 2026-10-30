variable "project" {
  type    = string
  default = "goldengoose"
}

variable "environment" {
  type    = string
  default = "dev"
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "vpc_cidr" {
  type    = string
  default = "10.60.0.0/16"
}

variable "api_image" {
  description = "Full image reference for the API/worker image (see .github/workflows/images.yml)"
  type        = string
}

variable "web_image" {
  description = "Full image reference for the web image"
  type        = string
}

variable "acm_certificate_arn" {
  description = <<-EOT
    ACM certificate ARN for HTTPS on the ALB. Empty (default) serves plain HTTP,
    acceptable only for a closed disposable test deploy; set it to add a 443
    listener and redirect 80->443.
  EOT
  type        = string
  default     = ""
}

variable "db_engine_version" {
  type    = string
  default = "18"
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "db_admin_password" {
  description = "RDS master password (role gg_admin; migrations run as this role)"
  type        = string
  sensitive   = true
}

variable "db_app_password" {
  description = "Password for the gg_app role the services connect as"
  type        = string
  sensitive   = true
}

variable "jwt_secret" {
  type      = string
  sensitive = true
}

variable "qdrant_url" {
  description = "Managed Qdrant endpoint (Qdrant Cloud or self-run); no in-VPC Qdrant in the skeleton"
  type        = string
}

variable "qdrant_api_key" {
  description = <<-EOT
    Qdrant API key. Qdrant Cloud requires one; a self-hosted/open Qdrant does
    not. Leave empty to skip the secret and its injection entirely — the app
    then connects without a key.
  EOT
  type        = string
  sensitive   = true
  default     = ""
}

variable "neo4j_uri" {
  description = "Managed Neo4j endpoint (Aura or marketplace image)"
  type        = string
}

variable "neo4j_user" {
  type    = string
  default = "neo4j"
}

variable "neo4j_password" {
  type      = string
  sensitive = true
}

variable "anthropic_api_key" {
  type      = string
  sensitive = true
  default   = ""
}

variable "voyage_api_key" {
  type      = string
  sensitive = true
  default   = ""
}

variable "google_api_key" {
  description = "Gemini key for OCR of scanned pages (GG_GOOGLE_API_KEY); required because GG_REQUIRE_REAL_PROVIDERS is true"
  type        = string
  sensitive   = true
  default     = ""
}
