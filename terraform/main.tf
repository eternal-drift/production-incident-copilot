# Small, real AWS footprint: S3 for runbook storage, IAM least-privilege
# role, and RDS PostgreSQL (pgvector-capable via engine version) as the
# AWS equivalent of the local pgvector setup. Per the plan: this is
# "conceptual/optional real provisioning" — it's fine to `terraform plan`
# and review without leaving RDS running permanently (it's the one
# resource here with a real ongoing cost, unlike S3/IAM/DynamoDB).

resource "aws_s3_bucket" "runbooks" {
  bucket = "${var.project_name}-runbooks-${var.environment}"
}

resource "aws_s3_bucket_versioning" "runbooks" {
  bucket = aws_s3_bucket.runbooks.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_public_access_block" "runbooks" {
  bucket                  = aws_s3_bucket.runbooks.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_db_subnet_group" "default" {
  name       = "${var.project_name}-db-subnet-${var.environment}"
  subnet_ids = data.aws_subnets.default.ids
}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

resource "aws_security_group" "rds" {
  name        = "${var.project_name}-rds-sg-${var.environment}"
  description = "Least-privilege: no ingress by default, add explicit rules for the app SG only"
  vpc_id      = data.aws_vpc.default.id
}

resource "aws_db_instance" "postgres" {
  identifier             = "${var.project_name}-db-${var.environment}"
  engine                 = "postgres"
  engine_version         = "16"
  instance_class         = "db.t4g.micro" # smallest instance — a demo, not production sizing
  allocated_storage      = 20
  db_name                = "incident_copilot"
  username               = "postgres"
  password               = var.db_password
  db_subnet_group_name   = aws_db_subnet_group.default.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  skip_final_snapshot    = true
  publicly_accessible    = false
  deletion_protection    = false # intentionally off for a demo project — flip on for anything real
}

data "aws_iam_policy_document" "app_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "app_role" {
  name               = "${var.project_name}-app-role-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.app_assume_role.json
}

data "aws_iam_policy_document" "app_permissions" {
  statement {
    sid       = "S3RunbookAccess"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
    resources = [aws_s3_bucket.runbooks.arn, "${aws_s3_bucket.runbooks.arn}/*"]
  }
}

resource "aws_iam_role_policy" "app_permissions" {
  name   = "${var.project_name}-app-permissions"
  role   = aws_iam_role.app_role.id
  policy = data.aws_iam_policy_document.app_permissions.json
}
