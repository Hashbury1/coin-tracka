output "api_alb_dns_name" {
  value       = aws_lb.api.dns_name
  description = "Point your API domain's DNS (CNAME/ALIAS) at this."
}

output "frontend_cloudfront_domain" {
  value       = aws_cloudfront_distribution.frontend.domain_name
  description = "Dashboard URL - point your frontend domain here, or use directly."
}

output "frontend_s3_bucket" {
  value       = aws_s3_bucket.frontend.id
  description = "Deploy target for `aws s3 sync frontend/ s3://<this>/`."
}

output "ecr_repository_urls" {
  value       = { for k, v in aws_ecr_repository.services : k => v.repository_url }
  description = "Push images here from CI; referenced by the ECS task definitions."
}

output "rds_endpoint" {
  value       = aws_db_instance.timescaledb.address
  description = "Run the TimescaleDB extension + init.sql against this after first apply - RDS doesn't run your db/init.sql automatically."
}

output "redis_primary_endpoint" {
  value = aws_elasticache_replication_group.redis.primary_endpoint_address
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.main.name
}

output "github_actions_role_arn" {
  value       = aws_iam_role.github_actions.arn
  description = "Set this as AWS_ROLE_ARN in your GitHub Actions workflow for OIDC-based deploys."
}

output "grafana_workspace_endpoint" {
  value       = try(aws_grafana_workspace.main.endpoint, null)
  description = "Only populated if IAM Identity Center is already enabled in the account - see cloudwatch.tf note."
}
