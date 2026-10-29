# Remote state (bootstrap before first shared apply)

The skeleton ships with local state so one operator can stand up a disposable
test deploy with no prerequisites. State is where Terraform records what it
created; if it lives only on a laptop, a second operator (or a teardown from
another machine) cannot see or destroy the stack. Move it to S3 before any
shared or repeated use.

Chicken-and-egg: the backend bucket must exist before `terraform init` can use
it, so it cannot be managed by this same configuration. Create it once, by hand,
then migrate:

```bash
export AWS_PROFILE=<profile>
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
BUCKET="goldengoose-tfstate-${ACCOUNT_ID}"

# 1. Create the state bucket, versioned and encrypted, public access blocked.
aws s3api create-bucket --bucket "$BUCKET" --region us-east-1
aws s3api put-bucket-versioning --bucket "$BUCKET" \
  --versioning-configuration Status=Enabled
aws s3api put-bucket-encryption --bucket "$BUCKET" \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
aws s3api put-public-access-block --bucket "$BUCKET" \
  --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

# 2. Uncomment the backend "s3" block in versions.tf, set bucket to $BUCKET,
#    then migrate the existing local state into it.
terraform init -migrate-state
```

Locking uses S3-native conditional writes (`use_lockfile = true`, Terraform
>= 1.10), so no DynamoDB lock table is required.

Teardown note: `scripts/teardown_aws.sh` destroys the application stack, not this
state bucket. Remove the state bucket by hand only after every environment that
used it is destroyed — it is versioned, so empty its versions first (the same
way the teardown script empties the app buckets).
