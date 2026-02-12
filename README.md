# Logicall AI - LiveKit Voice Agent on AWS EKS

A complete DevOps pipeline for deploying a LiveKit voice AI agent to Amazon EKS using Terraform, GitHub Actions, Argo CD, and External Secrets Operator.

## 🏗️ Architecture

```
┌─────────────────┐
│  GitHub Repo    │
│  (Source of     │
│   Truth)        │
└────────┬────────┘
         │
    ┌────┴────┐
    │         │
    ▼         ▼
┌────────┐ ┌──────────────┐
│  CI    │ │  Terraform   │
│Pipeline│ │  (EKS)       │
└────┬───┘ └──────┬───────┘
     │            │
     ▼            ▼
┌──────────┐  ┌──────────┐
│   ECR    │  │   EKS    │
│ (Images) │  │ (Cluster)│
└────┬─────┘  └────┬─────┘
     │             │
     └──────┬──────┘
            │
    ┌───────┴───────┐
    │               │
    ▼               ▼
┌──────────┐  ┌──────────────────┐
│ Argo CD  │  │ AWS Secrets      │
│ (GitOps) │  │ Manager          │
└────┬─────┘  └────────┬──────────┘
     │                 │
     │                 │
     ▼                 ▼
┌─────────────────────────────┐
│ External Secrets Operator    │
│ (Syncs secrets to K8s)       │
└──────────────┬──────────────┘
               │
               ▼
      ┌─────────────────┐
      │ LiveKit Agent   │
      │ Pods            │
      └────────┬────────┘
               │
               ▼
      ┌─────────────────┐
      │ LiveKit Cloud   │
      │ (Voice AI)       │
      └─────────────────┘
```

### Components

1. **Terraform** - Provisions EKS cluster, VPC, IAM roles, and networking
2. **GitHub Actions CI** - Builds Docker images, pushes to ECR, updates manifests
3. **Argo CD** - GitOps controller that syncs Kubernetes manifests from Git
4. **External Secrets Operator** - Syncs secrets from AWS Secrets Manager to Kubernetes
5. **AWS EKS** - Managed Kubernetes cluster
6. **AWS ECR** - Container registry for Docker images
7. **AWS Secrets Manager** - Secure secret storage
8. **LiveKit Cloud** - Voice AI infrastructure

## 📋 Prerequisites

- AWS Account with appropriate permissions
- GitHub repository (public or private)
- GitHub repository variables configured:
  - `AWS_ROLE_ARN` - IAM role ARN for GitHub Actions OIDC
  - `AWS_REGION` (optional, defaults to `us-east-1`)
  - `CLUSTER_NAME` (optional, defaults to `logicall-ai-cluster`)
- Terraform >= 1.6 (for local runs)
- AWS CLI configured (for local kubectl access)
- kubectl installed (for local access)

## 🚀 Quick Start

### 1. Configure GitHub Variables

Go to **Settings → Secrets and variables → Actions → Variables** and set:

- `AWS_ROLE_ARN`: `arn:aws:iam::YOUR_ACCOUNT_ID:role/GitHubActionsRole`
- `AWS_REGION`: `us-east-1` (optional)
- `CLUSTER_NAME`: `logicall-ai-cluster` (optional)

### 2. Deploy Infrastructure

The infrastructure is deployed automatically via GitHub Actions when you push to `main`, or you can trigger it manually:

1. Go to **Actions → Deploy EKS Cluster and Argo CD**
2. Click **Run workflow**
3. Wait for deployment (~7-10 minutes)

### 3. Access Services

After deployment, get your service URLs:

**Option 1: From GitHub Actions**
- Go to the latest workflow run
- Expand "Final Status and Credentials" step
- Copy the Argo CD URL and password

**Option 2: Using kubectl**
```bash
# Get Argo CD URL
kubectl get svc argocd-server -n argocd -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'

# Get Argo CD password
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d

# Get Backend URL
kubectl get svc backend -n apps -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'
```

**Option 3: Use the helper script**
```powershell
powershell -ExecutionPolicy Bypass -File get-urls.ps1
```

### 4. Set Up Secret Management (First Time Only)

This project uses **External Secrets Operator** to automatically sync secrets from **AWS Secrets Manager** to Kubernetes.

**Option A: Using the setup script (Recommended)**

```powershell
powershell -ExecutionPolicy Bypass -File setup-external-secrets.ps1
```

This script will:
1. Create/update the secret in AWS Secrets Manager from your `.env.local` file
2. Install External Secrets Operator (if not already installed)
3. Configure IAM role annotations

**Option B: Manual setup**

1. **Create secret in AWS Secrets Manager:**
   ```bash
   aws secretsmanager create-secret \
     --name livekit-agent-secrets \
     --secret-string '{"LIVEKIT_URL":"your-url","LIVEKIT_API_KEY":"your-key","LIVEKIT_API_SECRET":"your-secret"}' \
     --region us-east-1
   ```

2. **Get IAM role ARN from Terraform:**
   ```bash
   cd infra/eks
   terraform output external_secrets_iam_role_arn
   ```

3. **Update ServiceAccount with IAM role:**
   ```bash
   kubectl annotate serviceaccount external-secrets-sa \
     -n apps \
     eks.amazonaws.com/role-arn=arn:aws:iam::ACCOUNT_ID:role/CLUSTER_NAME-external-secrets-role \
     --overwrite
   ```

4. **Deploy ExternalSecret resource:**
   ```bash
   kubectl apply -f gitops/apps/backend/externalsecret.yaml
   ```

**Verify secret sync:**
```bash
kubectl get externalsecret livekit-credentials -n apps
kubectl get secret livekit-credentials -n apps
```

See [SECRET_MANAGEMENT.md](SECRET_MANAGEMENT.md) for detailed documentation.

### 5. Deploy Backend Application

The backend is automatically deployed when you:

1. Push changes to `src/`, `Dockerfile`, or `pyproject.toml`
2. Or manually trigger **Actions → CI - Build and Deploy Backend**

The CI pipeline will:
- Build Docker image
- Push to ECR
- Update `gitops/apps/backend/deployment.yaml` with new image tag
- Commit and push the change
- Argo CD automatically syncs the new image to the cluster

## 📁 Repository Structure

```
.
├── app/                          # Python FastAPI backend
│   └── main.py                   # FastAPI application
├── Dockerfile                    # Container image definition
├── requirements.txt              # Python dependencies
│
├── infra/                        # Infrastructure as Code
│   └── eks/
│       ├── main.tf               # EKS cluster, VPC, IAM
│       ├── variables.tf         # Terraform variables
│       └── terraform.tfvars     # Variable values
│
├── gitops/                       # GitOps manifests
│   ├── argocd/
│   │   └── root-app.yaml        # Argo CD Application
│   └── apps/
│       └── backend/
│           ├── deployment.yaml  # Kubernetes Deployment
│           ├── externalsecret.yaml # External Secrets Operator config
│           ├── external-secrets-sa.yaml # ServiceAccount for ESO
│           ├── service.yaml      # Kubernetes Service (commented out)
│           └── namespace.yaml   # Namespace definition
│
├── .github/
│   └── workflows/
│       ├── deploy.yml           # EKS + Argo CD deployment
│       └── ci-backend.yaml     # CI pipeline (build & deploy)
│
├── infra/eks/
│   ├── main.tf                  # EKS cluster, VPC, IAM
│   ├── external-secrets.tf      # External Secrets IAM role
│   ├── variables.tf             # Terraform variables
│   └── terraform.tfvars         # Variable values
│
└── *.ps1                         # Helper scripts (Windows)
```

## 🔄 Deployment Flow

### Initial Setup (One-time)

```
GitHub Actions (deploy.yml)
    ↓
Terraform Apply
    ↓
EKS Cluster Created
    ↓
Argo CD Installed
    ↓
root-app Applied
    ↓
Backend Namespace Created
```

### Application Updates (Every Push)

```
Code Change in app/
    ↓
GitHub Actions (ci-backend.yaml)
    ↓
Build Docker Image
    ↓
Push to ECR
    ↓
Update deployment.yaml (Git)
    ↓
Argo CD Detects Change
    ↓
Sync to Cluster
    ↓
New Pods Running
```

## 🔐 Accessing the Cluster

### Configure kubectl

```bash
aws eks update-kubeconfig \
  --region us-east-1 \
  --name logicall-ai-cluster \
  --role-arn arn:aws:iam::YOUR_ACCOUNT_ID:role/GitHubActionsRole
```

**Note:** Your IAM user needs permission to assume `GitHubActionsRole`, or you can access directly if your user is added to `aws-auth` ConfigMap.

### Verify Access

```bash
kubectl get nodes
kubectl get pods -n apps
kubectl get application root-app -n argocd
```

## 🌐 Service URLs

After deployment, you'll have:

- **Argo CD UI**: `https://<loadbalancer-dns>`
  - Username: `admin`
  - Password: (from workflow output or kubectl command above)

- **Backend API**: `http://<loadbalancer-dns>`
  - Health endpoint: `http://<loadbalancer-dns>/health`

## 🛠️ Helper Scripts

### Windows PowerShell Scripts

- `get-urls.ps1` - Get all service URLs and credentials
- `destroy-all.ps1` - Destroy all Terraform-managed resources
- `cleanup-orphaned-resources.ps1` - Clean up orphaned VPCs and resources
- `cleanup-elastic-ips.ps1` - Release unassociated Elastic IPs
- `check-costly-resources.ps1` - Check for resources that could cost money

### Usage Examples

```powershell
# Get service URLs
powershell -ExecutionPolicy Bypass -File get-urls.ps1

# Destroy everything
powershell -ExecutionPolicy Bypass -File destroy-all.ps1

# Check for costly resources
powershell -ExecutionPolicy Bypass -File check-costly-resources.ps1
```

## 🔧 Configuration

### Terraform Variables

Edit `infra/eks/terraform.tfvars` to customize:

- Cluster name
- Kubernetes version
- Node group size
- Instance types
- VPC CIDR blocks

### LiveKit Agent Configuration

The LiveKit agent is configured in `gitops/apps/backend/deployment.yaml`:

- **Replicas**: 1 (adjust as needed)
- **Resources**: 512Mi-1Gi memory, 250m-1000m CPU
- **Secrets**: Automatically injected from AWS Secrets Manager via External Secrets Operator
- **Mode**: Production (`start` command) - connects to LiveKit Cloud

**Note**: The agent connects outbound to LiveKit Cloud via WebSocket, so no Kubernetes Service/LoadBalancer is needed.

## 🐛 Troubleshooting

### Argo CD Application Not Syncing

1. Check Argo CD UI for error messages
2. Verify Git repository is accessible (if private, configure credentials)
3. Check application status:
   ```bash
   kubectl get application root-app -n argocd -o yaml
   ```

### Backend Pods Not Starting

1. Check pod status:
   ```bash
   kubectl get pods -n apps
   kubectl describe pod <pod-name> -n apps
   kubectl logs <pod-name> -n apps
   ```

2. Verify image exists in ECR:
   ```bash
   aws ecr describe-images --repository-name backend --region us-east-1
   ```

3. Check deployment:
   ```bash
   kubectl get deployment backend -n apps -o yaml
   ```

### Cannot Access Cluster

1. Verify AWS credentials:
   ```bash
   aws sts get-caller-identity
   ```

2. Update kubeconfig:
   ```bash
   aws eks update-kubeconfig --region us-east-1 --name logicall-ai-cluster
   ```

3. Check IAM permissions (user needs access in `aws-auth` ConfigMap)

## 🧹 Cleanup

### Destroy All Resources

```powershell
# Destroy Terraform-managed resources
powershell -ExecutionPolicy Bypass -File destroy-all.ps1

# Clean up orphaned resources
powershell -ExecutionPolicy Bypass -File cleanup-orphaned-resources.ps1

# Check for remaining costly resources
powershell -ExecutionPolicy Bypass -File check-costly-resources.ps1
```

### Manual Cleanup

If Terraform destroy fails:

1. Delete EKS cluster:
   ```bash
   aws eks delete-cluster --name logicall-ai-cluster --region us-east-1
   ```

2. Wait for cluster deletion, then clean up VPCs using `cleanup-orphaned-resources.ps1`

## 📝 Notes

- **GitOps Principle**: Never manually `kubectl apply` application manifests. All changes go through Git.
- **Image Updates**: CI pipeline automatically updates image tags. Manual edits will be overwritten.
- **State Management**: Terraform state is stored in S3: `logicall-ai-terraform-state-<account-id>`
- **Security**: No hardcoded credentials. All secrets use GitHub variables/secrets.

## 🔒 Security Considerations

- ✅ No hardcoded passwords or API keys
- ✅ Uses GitHub OIDC for AWS authentication
- ✅ Terraform state encrypted in S3
- ✅ IAM roles follow least privilege
- ✅ Secrets managed in AWS Secrets Manager (encrypted at rest)
- ✅ External Secrets Operator uses IRSA (no long-lived credentials)
- ✅ All secret access logged in CloudTrail
- ⚠️ AWS Account ID visible in some files (acceptable for public repos)
- ⚠️ IAM user names visible in Terraform config (low risk)

## 🔐 Secret Management

This project uses **External Secrets Operator** to automatically sync secrets from **AWS Secrets Manager** to Kubernetes.

### Benefits

- **No manual kubectl commands** - Secrets are managed in AWS
- **GitOps-friendly** - Secret definitions in Git, values in AWS
- **Automatic sync** - Secrets update automatically when changed in AWS
- **Secure** - Uses IAM Roles for Service Accounts (IRSA) for authentication
- **Audit trail** - All secret access is logged in CloudTrail

### Quick Setup

```powershell
# Run the setup script (reads from .env.local)
powershell -ExecutionPolicy Bypass -File setup-external-secrets.ps1
```

### Updating Secrets

```bash
# Update secret in AWS Secrets Manager
aws secretsmanager update-secret \
  --secret-id livekit-agent-secrets \
  --secret-string '{"LIVEKIT_URL":"...","LIVEKIT_API_KEY":"...","LIVEKIT_API_SECRET":"..."}' \
  --region us-east-1

# External Secrets will automatically sync within 1 hour
# Or force immediate sync by deleting/recreating the ExternalSecret
```

### Verifying Secrets

```bash
# Check ExternalSecret status
kubectl get externalsecret livekit-credentials -n apps

# Check Kubernetes secret
kubectl get secret livekit-credentials -n apps

# View secret details
kubectl describe externalsecret livekit-credentials -n apps
```

For detailed documentation, see [SECRET_MANAGEMENT.md](SECRET_MANAGEMENT.md).

## 📚 Additional Resources

- [Terraform AWS EKS Module](https://registry.terraform.io/modules/terraform-aws-modules/eks/aws/)
- [Argo CD Documentation](https://argo-cd.readthedocs.io/)
- [LiveKit Agents Documentation](https://docs.livekit.io/agents/)
- [External Secrets Operator](https://external-secrets.io/)
- [AWS Secrets Manager](https://docs.aws.amazon.com/secretsmanager/)
- [AWS EKS Best Practices](https://aws.github.io/aws-eks-best-practices/)

## 📄 License

[Add your license here]

---

**Built with ❤️ using Terraform, GitHub Actions, Argo CD, and AWS EKS**

