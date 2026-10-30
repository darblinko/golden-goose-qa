variable "project" {
  type    = string
  default = "goldengoose"
}

variable "environment" {
  type    = string
  default = "dev"
}

variable "location" {
  type    = string
  default = "eastus2"
}

variable "api_image" {
  description = "Full image reference for the API/worker image (see .github/workflows/images.yml)"
  type        = string
}

variable "web_image" {
  description = "Full image reference for the web image"
  type        = string
}

variable "db_admin_password" {
  description = "Flexible-server admin password (role gg_admin; migrations run as this role)"
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
  description = "Managed Qdrant endpoint (Qdrant Cloud or self-run); no in-cluster Qdrant in the skeleton"
  type        = string
}

variable "neo4j_uri" {
  description = "Managed Neo4j endpoint (Aura or marketplace VM)"
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

# Blob has no native S3 API (storage.tf). These point the S3ObjectStore at an
# S3 gateway in front of Blob; left empty, document access fails at runtime.
variable "s3_gateway_endpoint_url" {
  type    = string
  default = ""
}

variable "s3_gateway_access_key" {
  type    = string
  default = ""
}

variable "s3_gateway_secret_key" {
  type      = string
  sensitive = true
  default   = ""
}
