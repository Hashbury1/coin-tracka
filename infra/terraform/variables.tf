variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "project_name" {
  type    = string
  default = "coin-tracka"
}

variable "environment" {
  type    = string
  default = "staging"
}

variable "db_instance_class" {
  type    = string
  default = "db.t3.small"
}

variable "db_multi_az" {
  type        = bool
  default     = true
  description = "Enable synchronous standby in a second AZ with automatic failover."
}

variable "redis_node_type" {
  type    = string
  default = "cache.t6g.micro"
}

variable "db_password" {
  type      = string
  sensitive = true
}

# ECS / container sizing
variable "api_task_cpu" {
  type    = number
  default = 256 # 0.25 vCPU - Fargate minimum
}

variable "api_task_memory" {
  type    = number
  default = 512
}

variable "api_desired_count" {
  type    = number
  default = 1
}

variable "api_max_count" {
  type        = number
  default     = 4
  description = "Ceiling for autoscaling the API service."
}

# CloudWatch Logs
variable "log_retention_days" {
  type    = number
  default = 7
}

# GitHub OIDC (for CI/CD to assume an AWS role without static keys)
variable "github_org" {
  type        = string
  description = "GitHub org/user that owns the repo, e.g. \"Hashbury1\"."
}

variable "github_repo" {
  type        = string
  default     = "coin-tracka"
  description = "Repo name only (no owner prefix)."
}

# Alerting
variable "alert_email" {
  type        = string
  default     = ""
  description = "Optional email for CloudWatch alarm notifications."
}

# TLS 
variable "acm_certificate_arn" {
  type        = string
  description = "ACM certificate ARN for the ALB's HTTPS listener. Must be in the same region as aws_region (ALB certs, unlike CloudFront, are NOT required to be us-east-1). Request one via ACM for your domain before applying."
}

# Third-party API keys (mirrors .env locally)
variable "birdeye_api_key" {
  type      = string
  sensitive = true
}

variable "moralis_api_key" {
  type      = string
  sensitive = true
}
