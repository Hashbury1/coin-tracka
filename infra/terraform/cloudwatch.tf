# ---------------- Log groups (7-day retention - short on purpose for a
# portfolio project; bump to 30+ days for anything you'd actually debug
# incidents from a week later) ----------------
resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${var.project_name}-${var.environment}/api"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "workers" {
  for_each          = toset(["ingestion", "scoring"])
  name              = "/ecs/${var.project_name}-${var.environment}/${each.key}"
  retention_in_days = var.log_retention_days
}

# ---------------- Alerting: SNS topic + a couple of baseline alarms ----------------
# Mirrors the intent of the 6 Prometheus alert rules from the local stack
# (ScoringStalled, HighAPIErrorRate, ServiceDown, etc.) but using native
# CloudWatch metrics so this works even before/instead of standing up
# Managed Grafana below.
resource "aws_sns_topic" "alerts" {
  name = "${var.project_name}-${var.environment}-alerts"
}

resource "aws_sns_topic_subscription" "alerts_email" {
  count     = var.alert_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_cloudwatch_metric_alarm" "api_service_unhealthy" {
  alarm_name          = "${var.project_name}-${var.environment}-api-unhealthy-targets"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  metric_name         = "HealthyHostCount"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Minimum"
  threshold           = 1
  alarm_description   = "No healthy API targets behind the ALB - the /health check is failing."
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]

  dimensions = {
    TargetGroup  = aws_lb_target_group.api.arn_suffix
    LoadBalancer = aws_lb.api.arn_suffix
  }
}

resource "aws_cloudwatch_metric_alarm" "api_5xx_rate" {
  alarm_name          = "${var.project_name}-${var.environment}-api-5xx"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "HTTPCode_Target_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = 300
  statistic           = "Sum"
  threshold           = 10
  alarm_description   = "Elevated 5xx rate from the API - mirrors the local HighAPIErrorRate Prometheus rule."
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"

  dimensions = {
    LoadBalancer = aws_lb.api.arn_suffix
  }
}

resource "aws_cloudwatch_metric_alarm" "db_high_connections" {
  alarm_name          = "${var.project_name}-${var.environment}-rds-connections"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "DatabaseConnections"
  namespace           = "AWS/RDS"
  period              = 60
  statistic           = "Average"
  threshold           = 40 # db.t3.small's default max_connections is well above this; tune once you know real usage
  alarm_description   = "RDS connection count climbing - possible connection leak or retry storm."
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.timescaledb.identifier
  }
}

# ---------------- Amazon Managed Grafana ----------------
# NOTE: Managed Grafana requires AWS IAM Identity Center (SSO) to be
# enabled in the account for user authentication - that's an account-level
# prerequisite Terraform can't fully automate here (it's a one-time
# console/org setup). This resource assumes that's already done; if not,
# either enable IAM Identity Center first, or skip this and keep running
# the existing self-hosted Grafana container from docker-compose, pointed
# at CloudWatch as an additional data source instead.
resource "aws_grafana_workspace" "main" {
  name                     = "${var.project_name}-${var.environment}"
  account_access_type      = "CURRENT_ACCOUNT"
  authentication_providers = ["AWS_SSO"]
  permission_type          = "SERVICE_MANAGED"
  data_sources             = ["CLOUDWATCH"]
  role_arn                 = aws_iam_role.grafana.arn
}

resource "aws_iam_role" "grafana" {
  name = "${var.project_name}-${var.environment}-grafana"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "grafana.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "grafana_cloudwatch" {
  role       = aws_iam_role.grafana.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchReadOnlyAccess"
}
