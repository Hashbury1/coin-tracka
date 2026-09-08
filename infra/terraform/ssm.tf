# Replaces the local .env file for anything sensitive. Values are written
# here as Terraform variables for a first apply, but day-to-day rotation
# should happen directly in the console/CLI, not via `terraform apply` -
# otherwise every rotation shows up as a plan diff and secrets risk
# landing in state/plan output.

resource "aws_ssm_parameter" "db_username" {
  name  = "/${var.project_name}/${var.environment}/db_username"
  type  = "String"
  value = "coin-tracka"
}

resource "aws_ssm_parameter" "db_password" {
  name  = "/${var.project_name}/${var.environment}/db_password"
  type  = "SecureString"
  value = var.db_password
}

resource "aws_ssm_parameter" "birdeye_api_key" {
  name  = "/${var.project_name}/${var.environment}/birdeye_api_key"
  type  = "SecureString"
  value = var.birdeye_api_key
}

resource "aws_ssm_parameter" "moralis_api_key" {
  name  = "/${var.project_name}/${var.environment}/moralis_api_key"
  type  = "SecureString"
  value = var.moralis_api_key
}
