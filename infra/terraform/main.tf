terraform {
  required_version = ">= 1.7"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Remote state - swap for your own bucket/table before applying.
  backend "s3" {
    bucket         = "meme-tracker"
    key            = "meme-tracker/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "meme-tracker-tf-locks"
    encrypt        = true
  }
}

provider "aws" {
  region = var.aws_region
}

# ---------------- Networking ----------------
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = "${var.project_name}-${var.environment}"
  cidr = "10.0.0.0/16"

  azs             = data.aws_availability_zones.available.names
  private_subnets = ["10.0.1.0/24", "10.0.2.0/24"]
  public_subnets  = ["10.0.101.0/24", "10.0.102.0/24"]

  enable_nat_gateway = true
  single_nat_gateway = var.environment != "production"
}

data "aws_availability_zones" "available" {
  state = "available"
}

# ---------------- Container registry ----------------
resource "aws_ecr_repository" "services" {
  for_each             = toset(["ingestion", "scoring", "api"])
  name                 = "${var.project_name}/${each.key}"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

# ---------------- Managed Postgres (RDS, TimescaleDB extension enabled manually post-provision) ----------------
resource "aws_db_instance" "timescaledb" {
  identifier             = "${var.project_name}-${var.environment}"
  engine                 = "postgres"
  engine_version         = "16.4"
  instance_class         = var.db_instance_class
  allocated_storage      = 20
  db_name                = "meme_tracker"
  username               = "meme_admin"
  password               = var.db_password # inject via TF_VAR_db_password, never commit
  vpc_security_group_ids = [aws_security_group.db.id]
  db_subnet_group_name   = module.vpc.database_subnet_group_name
  skip_final_snapshot    = var.environment != "production"
  storage_encrypted      = true
}

resource "aws_security_group" "db" {
  name_prefix = "${var.project_name}-db-"
  vpc_id      = module.vpc.vpc_id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
  }
}

resource "aws_security_group" "app" {
  name_prefix = "${var.project_name}-app-"
  vpc_id      = module.vpc.vpc_id
}

# ---------------- ElastiCache Redis ----------------
resource "aws_elasticache_cluster" "redis" {
  cluster_id           = "${var.project_name}-${var.environment}"
  engine               = "redis"
  node_type            = var.redis_node_type
  num_cache_nodes      = 1
  parameter_group_name = "default.redis7"
  security_group_ids   = [aws_security_group.app.id]
}

# NOTE: ECS/EKS service + task definitions, ALB, and IAM roles are
# intentionally left out of this stub to keep it readable — in a real
# deploy these would live in modules/ecs-service per microservice,
# parameterized by the ECR repo URIs above.
