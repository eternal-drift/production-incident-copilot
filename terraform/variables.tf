variable "aws_region" {
  type    = string
  default = "eu-west-1" # Ireland — matches target market
}
variable "project_name" {
  type    = string
  default = "incident-copilot"
}
variable "environment" {
  type    = string
  default = "demo"
}
variable "db_password" {
  description = "RDS master password. Pass via TF_VAR_db_password env var, never commit it."
  type        = string
  sensitive   = true
  default     = "" # deliberately blank; plan will fail loudly if not supplied, forcing a conscious choice
}
