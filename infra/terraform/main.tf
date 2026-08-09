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
    bucket         = "meme-tracker-tfstate-CHANGE-ME"
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
  multi_az               = var.db_multi_az
  allocated_storage      = 20
  max_allocated_storage  = 100 # allows storage autoscaling rather than a hard cap
  db_name                = "meme_tracker"
  username               = "meme_admin"
  password               = var.db_password # inject via TF_VAR_db_password, never commit
  vpc_security_group_ids = [aws_security_group.db.id]
  db_subnet_group_name   = module.vpc.database_subnet_group_name
  skip_final_snapshot    = var.environment != "production"
  storage_encrypted      = true

  # Multi-AZ gives you a synchronously-replicated standby in a second AZ
  # that RDS fails over to automatically on primary failure/patching -
  # this is what actually justifies the cost jump over a single instance.
  backup_retention_period = var.environment == "production" ? 7 : 1
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

# ---------------- ElastiCache Redis (dedicated node) ----------------
resource "aws_elasticache_replication_group" "redis" {
  replication_group_id = "${var.project_name}-${var.environment}"
  description           = "Redis Streams broker for ingestion -> scoring"
  engine                = "redis"
  engine_version        = "7.1"
  node_type             = var.redis_node_type
  num_cache_clusters    = 1
  parameter_group_name  = "default.redis7"
  subnet_group_name     = aws_elasticache_subnet_group.redis.name
  security_group_ids    = [aws_security_group.app.id]
  automatic_failover_enabled = false # single dedicated node; set true + num_cache_clusters=2 for prod HA
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
}

resource "aws_elasticache_subnet_group" "redis" {
  name       = "${var.project_name}-${var.environment}-redis"
  subnet_ids = module.vpc.private_subnets
}

resource "aws_security_group_rule" "redis_ingress" {
  type                     = "ingress"
  from_port                = 6379
  to_port                  = 6379
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.app.id
  security_group_id        = aws_security_group.app.id
}

# NOTE: ECS/EKS service + task definitions, ALB, and IAM roles are
# intentionally left out of this stub to keep it readable — in a real
# deploy these would live in modules/ecs-service per microservice,
# parameterized by the ECR repo URIs above.
