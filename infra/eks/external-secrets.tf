# OIDC Provider for IRSA (IAM Roles for Service Accounts)
# EKS automatically creates an OIDC provider, but we need to ensure it exists
# Get the OIDC issuer URL from the cluster
locals {
  oidc_provider_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/${replace(aws_eks_cluster.main.identity[0].oidc[0].issuer, "https://", "")}"
  oidc_issuer_url   = replace(aws_eks_cluster.main.identity[0].oidc[0].issuer, "https://", "")
}

data "aws_caller_identity" "current" {}

# IAM Role for External Secrets Operator to access AWS Secrets Manager
resource "aws_iam_role" "external_secrets" {
  name = "${var.cluster_name}-external-secrets-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Federated = local.oidc_provider_arn
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "${local.oidc_issuer_url}:sub" = "system:serviceaccount:apps:external-secrets-sa"
            "${local.oidc_issuer_url}:aud"  = "sts.amazonaws.com"
          }
        }
      }
    ]
  })

  tags = var.tags
}

# Policy for External Secrets to read from AWS Secrets Manager
resource "aws_iam_role_policy" "external_secrets" {
  name = "${var.cluster_name}-external-secrets-policy"
  role = aws_iam_role.external_secrets.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret"
        ]
        Resource = "arn:aws:secretsmanager:${var.aws_region}:*:secret:livekit-agent-secrets*"
      },
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:ListSecrets"
        ]
        Resource = "*"
      }
    ]
  })
}

# OIDC Provider for IRSA (if not already exists)
resource "aws_iam_openid_connect_provider" "eks" {
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["9e99a48a9960b14926bb7f3b02e22da2b0ab7280"]
  url              = aws_eks_cluster.main.identity[0].oidc[0].issuer

  tags = var.tags
}

# Output the IAM role ARN for use in Kubernetes ServiceAccount
output "external_secrets_iam_role_arn" {
  description = "IAM Role ARN for External Secrets Operator"
  value       = aws_iam_role.external_secrets.arn
}

