output "alb_dns_name" {
  value = aws_lb.main.dns_name
}

output "database_endpoint" {
  value = aws_db_instance.main.address
}

output "bucket_names" {
  value = { for k, b in aws_s3_bucket.main : k => b.bucket }
}

output "cognito_issuer" {
  description = "OIDC issuer for the auth seam swap (ADR 0020)"
  value       = "https://cognito-idp.${var.region}.amazonaws.com/${aws_cognito_user_pool.main.id}"
}

output "cognito_client_id" {
  value = aws_cognito_user_pool_client.web.id
}
