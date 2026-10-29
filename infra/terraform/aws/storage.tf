# Object store seam: native S3 replaces SeaweedFS. Services run with
# GG_S3_ENDPOINT_URL and GG_S3_ACCESS_KEY empty, so the boto3 default chain
# picks up the ECS task role.

locals {
  buckets = {
    documents = "${local.name}-documents"
    artifacts = "${local.name}-artifacts"
    backups   = "${local.name}-backups"
  }
}

resource "aws_s3_bucket" "main" {
  for_each = local.buckets

  bucket = each.value
}

# Versioning only — deliberately no Object Lock/immutability. Object Lock would
# harden a durable environment against tampering, but a retention-locked bucket
# cannot be emptied until its retention elapses, which blocks scripts/teardown_aws.sh
# from cleanly removing this disposable test deploy. For a durable environment,
# add object_lock_configuration and drop the destroy-time bucket emptying.
resource "aws_s3_bucket_versioning" "main" {
  for_each = aws_s3_bucket.main

  bucket = each.value.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "main" {
  for_each = aws_s3_bucket.main

  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "main" {
  for_each = aws_s3_bucket.main

  bucket = each.value.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}
