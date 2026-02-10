terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.23"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.11"
    }
  }

  # Backend configuration - update this after bootstrap
  # backend "s3" {
  #   bucket         = "REPLACE_WITH_STATE_BUCKET"
  #   key            = "eks/terraform.tfstate"
  #   region         = "REPLACE_WITH_REGION"
  #   dynamodb_table = "REPLACE_WITH_LOCK_TABLE"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.aws_region
}

# VPC
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = "${var.cluster_name}-vpc"
  cidr = var.vpc_cidr

  azs             = var.availability_zones
  public_subnets  = var.public_subnet_cidrs
  private_subnets = var.private_subnet_cidrs

  enable_nat_gateway   = true
  single_nat_gateway   = var.single_nat_gateway
  enable_dns_hostnames = true
  enable_dns_support   = true

  public_subnet_tags = {
    "kubernetes.io/role/elb" = "1"
  }

  private_subnet_tags = {
    "kubernetes.io/role/internal-elb" = "1"
  }

  tags = var.tags
}

# EKS Cluster
resource "aws_eks_cluster" "main" {
  name     = var.cluster_name
  role_arn = aws_iam_role.cluster.arn
  version  = var.kubernetes_version

  vpc_config {
    subnet_ids              = concat(module.vpc.public_subnets, module.vpc.private_subnets)
    endpoint_private_access = true
    endpoint_public_access  = true
    public_access_cidrs     = var.cluster_endpoint_public_access_cidrs
  }

  enabled_cluster_log_types = ["api", "audit", "authenticator", "controllerManager", "scheduler"]

  depends_on = [
    aws_cloudwatch_log_group.cluster,
    aws_iam_role_policy_attachment.cluster_AmazonEKSClusterPolicy,
  ]

  tags = var.tags
}

resource "aws_cloudwatch_log_group" "cluster" {
  name              = "/aws/eks/${var.cluster_name}/cluster"
  retention_in_days = 7

  tags = var.tags
}

# EKS Cluster IAM Role
resource "aws_iam_role" "cluster" {
  name = "${var.cluster_name}-cluster-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "eks.amazonaws.com"
        }
      }
    ]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "cluster_AmazonEKSClusterPolicy" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
  role       = aws_iam_role.cluster.name
}

# Fargate Profile for kube-system (CoreDNS)
resource "aws_eks_fargate_profile" "kube_system" {
  cluster_name           = aws_eks_cluster.main.name
  fargate_profile_name   = "kube-system"
  pod_execution_role_arn = aws_iam_role.fargate_pod_execution.arn
  subnet_ids             = module.vpc.private_subnets

  selector {
    namespace = "kube-system"
    labels = {
      "k8s-app" = "kube-dns"
    }
  }

  tags = var.tags
}

# Fargate Profile for apps namespace
resource "aws_eks_fargate_profile" "apps" {
  cluster_name           = aws_eks_cluster.main.name
  fargate_profile_name   = "apps"
  pod_execution_role_arn = aws_iam_role.fargate_pod_execution.arn
  subnet_ids             = module.vpc.private_subnets

  selector {
    namespace = "apps"
  }

  tags = var.tags
}

# Fargate Profile for argocd namespace
resource "aws_eks_fargate_profile" "argocd" {
  cluster_name           = aws_eks_cluster.main.name
  fargate_profile_name   = "argocd"
  pod_execution_role_arn = aws_iam_role.fargate_pod_execution.arn
  subnet_ids             = module.vpc.private_subnets

  selector {
    namespace = "argocd"
  }

  tags = var.tags
}

# Fargate Pod Execution Role
resource "aws_iam_role" "fargate_pod_execution" {
  name = "${var.cluster_name}-fargate-pod-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "eks-fargate-pods.amazonaws.com"
        }
      }
    ]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "fargate_pod_execution" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSFargatePodExecutionRolePolicy"
  role       = aws_iam_role.fargate_pod_execution.name
}

# EKS Add-ons
resource "aws_eks_addon" "coredns" {
  cluster_name             = aws_eks_cluster.main.name
  addon_name               = "coredns"
  addon_version            = "v1.11.1-eksbuild.4"
  resolve_conflicts_on_update = "OVERWRITE"

  configuration_values = jsonencode({
    computeType = "fargate"
  })

  depends_on = [
    aws_eks_fargate_profile.kube_system,
  ]

  tags = var.tags
}

resource "aws_eks_addon" "vpc_cni" {
  cluster_name             = aws_eks_cluster.main.name
  addon_name               = "vpc-cni"
  addon_version            = "v1.16.0-eksbuild.1"
  resolve_conflicts_on_update = "OVERWRITE"

  tags = var.tags
}

resource "aws_eks_addon" "kube_proxy" {
  cluster_name             = aws_eks_cluster.main.name
  addon_name               = "kube-proxy"
  # Let AWS automatically select the compatible version for the cluster
  resolve_conflicts_on_update = "OVERWRITE"

  tags = var.tags
}

# Security group rule to allow inbound traffic from load balancers
# This allows HTTP/HTTPS traffic to reach pods through load balancers
resource "aws_security_group_rule" "cluster_ingress_http" {
  description       = "Allow HTTP traffic from load balancers"
  type              = "ingress"
  from_port         = 80
  to_port           = 80
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_eks_cluster.main.vpc_config[0].cluster_security_group_id
}

resource "aws_security_group_rule" "cluster_ingress_https" {
  description       = "Allow HTTPS traffic from load balancers"
  type              = "ingress"
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_eks_cluster.main.vpc_config[0].cluster_security_group_id
}

# Kubernetes provider (for post-creation resources)
data "aws_eks_cluster_auth" "main" {
  name = aws_eks_cluster.main.name
}

provider "kubernetes" {
  host                   = aws_eks_cluster.main.endpoint
  cluster_ca_certificate = base64decode(aws_eks_cluster.main.certificate_authority[0].data)
  token                  = data.aws_eks_cluster_auth.main.token
}

provider "helm" {
  kubernetes {
    host                   = aws_eks_cluster.main.endpoint
    cluster_ca_certificate = base64decode(aws_eks_cluster.main.certificate_authority[0].data)
    token                  = data.aws_eks_cluster_auth.main.token
  }
}

# Add GitHub Actions role to aws-auth ConfigMap
data "aws_iam_role" "github_actions" {
  name = "GitHubActionsRole"
}

# Get existing aws-auth ConfigMap
data "kubernetes_config_map_v1" "aws_auth" {
  metadata {
    name      = "aws-auth"
    namespace = "kube-system"
  }
  depends_on = [aws_eks_cluster.main]
}

# Update aws-auth ConfigMap to include GitHub Actions role
resource "kubernetes_config_map_v1_data" "aws_auth" {
  metadata {
    name      = "aws-auth"
    namespace = "kube-system"
  }

  data = {
    mapRoles = yamlencode(concat(
      try(yamldecode(data.kubernetes_config_map_v1.aws_auth.data["mapRoles"]), []),
      [{
        rolearn  = data.aws_iam_role.github_actions.arn
        username = "github-actions"
        groups   = ["system:masters"]
      }]
    ))
  }

  force = true

  depends_on = [
    aws_eks_cluster.main,
    data.kubernetes_config_map_v1.aws_auth,
  ]
}

# Note: apps namespace will be created by Argo CD root application
# (which has CreateNamespace=true in syncOptions)
# We don't need to create it here via Terraform to avoid Kubernetes API auth issues in CI

