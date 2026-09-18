output "runbooks_bucket_name" { value = aws_s3_bucket.runbooks.bucket }
output "app_role_arn" { value = aws_iam_role.app_role.arn }
output "rds_endpoint" {
  value     = aws_db_instance.postgres.endpoint
  sensitive = true
}
