# Logicall AI - LiveKit Voice Agent on AWS EKS

A configurable LiveKit voice AI agent with DynamoDB-driven profiles, deployed to Amazon EKS. Includes an outbound-call trigger API (FastAPI + AWS Lambda). The repo provides a full DevOps pipeline using Terraform, GitHub Actions, Argo CD, and External Secrets Operator.

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
└────┬─────┘  └────────┬─────────┘
     │                 │
     │                 │
     ▼                 ▼
┌─────────────────────────────┐
│ External Secrets Operator   │
│ (Syncs secrets to K8s)      │
└──────────────┬──────────────┘
               │
               ▼
      ┌─────────────────┐
      │ LiveKit Agent   │
      │ Pods            │
      │ (Auto-scaled)   │
      └────────┬────────┘
               │
               │
      ┌────────┴────────┐
      │                 │
      ▼                 ▼
┌────────────┐    ┌──────────────┐
│   HPA      │◄───│   Metrics    │
│(Autoscaler)│    │   Server     │
└────────────┘    └──────────────┘
      │
      │
      ▼
┌────────────────┐
│ LiveKit Cloud  │
│ (Voice AI)     │
└────────────────┘
```

### Components

1. **LiveKit Agent** (`src/`) - Configurable voice agent; profiles and presets stored in **DynamoDB**
2. **Outbound Trigger API** (`api/outbound_trigger/`) - FastAPI app (Mangum) to dispatch outbound calls; deployable as **AWS Lambda**
3. **Terraform** - Provisions EKS cluster, VPC, IAM roles, and networking
4. **GitHub Actions** - CI builds agent image and deploys to ECR; separate workflow deploys API services to Lambda
5. **Argo CD** - GitOps controller that syncs Kubernetes manifests from Git
6. **External Secrets Operator** - Syncs secrets from AWS Secrets Manager to Kubernetes
7. **Horizontal Pod Autoscaler (HPA)** - Scales agent pods by CPU/memory
8. **Metrics Server** - Resource metrics for HPA
9. **AWS EKS / ECR / Secrets Manager** - Cluster, container registry, and secret storage
10. **LiveKit Cloud** - Voice AI infrastructure

## 📋 Prerequisites
- **Python** 3.10–3.14 (project uses [uv](https://docs.astral.sh/uv/) for dependencies)
- **AWS Account** with appropriate permissions
- **GitHub** repository variables:
  - `AWS_ROLE_ARN` - IAM role ARN for GitHub Actions OIDC
  - `AWS_REGION` (optional, defaults to `us-east-1`)
  - `CLUSTER_NAME` (optional, defaults to `logicall-ai-cluster`)
- **Terraform** >= 1.6 (for local infra runs)
- **AWS CLI** and **kubectl** (for cluster access)

## 🚀 Quick Start

### 1. Configure GitHub Variables

Go to **Settings → Secrets and variables → Actions → Variables** and set:

- `AWS_ROLE_ARN`: `arn:aws:iam::YOUR_ACCOUNT_ID:role/GitHubActionsRole`
- `AWS_REGION`: `us-east-1` (optional)
- `CLUSTER_NAME`: `logicall-ai-cluster` (optional)

### 2. Deploy Infrastructure

EKS and Argo CD are deployed via **manual** workflow dispatch (the workflow is disabled for automatic runs):

1. Go to **Actions → Deploy EKS Cluster and Argo CD (DISABLED)**
2. Click **Run workflow**, set the confirm input to `deploy-eks`
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

# Get Backend/LoadBalancer URL (if a Service exists)
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
     --secret-string '{"LIVEKIT_URL":"your-url","LIVEKIT_API_KEY":"your-key","LIVEKIT_API_SECRET":"your-secret","OPENAI_API_KEY":"your-openai-key","ANTHROPIC_API_KEY":"your-anthropic-key"}' \
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

See the **Secret Management** section below; a separate `SECRET_MANAGEMENT.md` may exist for deeper detail.

### 5. Deploy Agent and API

- **LiveKit agent (EKS)**  
  Pushes to `src/`, `Dockerfile`, or `pyproject.toml` on `main` trigger **CI - Build and Deploy Backend**: build image, push to ECR (`backend` repo), update `gitops/apps/backend/deployment.yaml`, then Argo CD syncs the `livekit-agent` deployment.

- **Outbound trigger API (Lambda)**  
  Pushes under `api/**` trigger **Deploy API Services (Lambda)** to deploy the FastAPI outbound-trigger app as Lambda.

## 📁 Repository Structure

```
.
├── src/                          # LiveKit voice agent
│   ├── agent.py                  # Agent entrypoint (cli, start/dev)
│   ├── session_builder.py        # Session/config wiring
│   ├── config.py                 # Configuration dataclasses
│   ├── profile_resolver.py       # DynamoDB profile resolution
│   └── tools.py                  # Agent tools
│
├── api/                          # API services
│   ├── run_local.py              # Run any API locally (e.g. outbound_trigger)
│   ├── common/                   # Shared helpers (secrets, LiveKit client)
│   └── outbound_trigger/         # Outbound-call trigger (FastAPI + Mangum → Lambda)
│       ├── main.py
│       ├── requirements.txt
│       └── src/routes/trigger.py
│
├── migrations/                   # DynamoDB migrations (agent profiles)
│   ├── README.md
│   ├── run_migrations.py
│   ├── 001_create_table.py
│   ├── 002_seed_defaults.py
│   └── table-definition.json
│
├── Dockerfile                    # Agent image (uv, Python 3.13)
├── docker-compose.yml            # Local agent in dev mode
├── pyproject.toml                # Dependencies (uv); no top-level requirements.txt
├── uv.lock
│
├── infra/eks/                    # Terraform
│   ├── main.tf
│   ├── external-secrets.tf
│   ├── variables.tf
│   └── terraform.tfvars
│
├── gitops/
│   ├── argocd/root-app.yaml
│   └── apps/backend/
│       ├── deployment.yaml       # livekit-agent Deployment
│       ├── hpa.yaml
│       ├── externalsecret.yaml
│       ├── external-secrets-sa.yaml
│       ├── service.yaml
│       └── namespace.yaml
│
├── .github/workflows/
│   ├── deploy.yml                # EKS + Argo CD (manual dispatch)
│   ├── ci-backend.yaml           # Build & deploy agent image to EKS
│   └── deploy-api.yml            # Deploy API services (e.g. Lambda)
│
└── *.ps1                         # Helper scripts (see Helper Scripts)
```

## 🖥️ Local Development

### Agent (LiveKit)

- **With Docker:**  
  `docker-compose up` runs the agent in **dev** mode (connects to LiveKit Cloud). Ensure `.env.local` exists with `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, and any TTS/STT keys (OpenAI, Anthropic, etc.).

- **With uv:**  
  From repo root: `uv sync` then `uv run -m src.agent dev`.

### Outbound trigger API

Run the FastAPI app locally (default port 8010):

```bash
# From repo root (requires uvicorn in path or install api deps)
python api/run_local.py outbound_trigger
# Optional: --port 9000 --host 127.0.0.1
```

Docs at `http://127.0.0.1:8010/docs`.

### DynamoDB (profiles)

Agent configuration is driven by DynamoDB. Run migrations once (see `migrations/README.md`):

```bash
python migrations/run_migrations.py
```

Set `DYNAMODB_TABLE_NAME` (default `logicall_agent_config`) and `AWS_REGION` in `.env.local` or environment.

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

**Agent (EKS):**
```
Change in src/, Dockerfile, or pyproject.toml
    → CI - Build and Deploy Backend
    → Build image → ECR → update deployment.yaml → Argo CD syncs livekit-agent
```

**API (Lambda):**
```
Change in api/**
    → Deploy API Services (Lambda)
    → Deploy outbound_trigger (and other API services) to Lambda
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

- **Backend/API** (if a Service is configured): `http://<loadbalancer-dns>`  
  The LiveKit agent itself connects outbound to LiveKit Cloud and does not expose HTTP. The outbound trigger API is deployed as Lambda (see **Deploy API Services** workflow).

## 🛠️ Helper Scripts

### Windows PowerShell Scripts

- `get-urls.ps1` - Get service URLs and credentials (Argo CD, backend)
- `destroy-all.ps1` - Destroy Terraform-managed resources
- `setup-external-secrets.ps1` - Configure External Secrets from `.env.local`
- `create-livekit-secret.ps1` - Create/update LiveKit secret in AWS Secrets Manager
- `test-docker.ps1` - Test agent Docker build/run
- `test-agent.ps1` - Test agent locally
- `check-costly-resources.ps1` - List resources that may incur cost
- `cleanup-orphaned-resources.ps1` - Clean orphaned VPCs/resources
- `cleanup-elastic-ips.ps1` - Release unassociated Elastic IPs
- `cleanup-terraform-state.ps1` - Clean Terraform state
- `cleanup-vpcs.ps1` - Clean up VPCs

**Migrations:** `migrations/create_table.ps1`, `migrations/create_table_aws_cli.ps1`, `migrations/quick_setup.ps1`

### Usage Examples

```powershell
# Get service URLs
powershell -ExecutionPolicy Bypass -File get-urls.ps1

# Destroy everything
powershell -ExecutionPolicy Bypass -File destroy-all.ps1

# Setup external secrets (from .env.local)
powershell -ExecutionPolicy Bypass -File setup-external-secrets.ps1

# Check costly resources
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

The agent runs as the **livekit-agent** Deployment; its spec is in `gitops/apps/backend/deployment.yaml`:

- **Replicas**: Managed by HPA (1-10 pods, auto-scaled)
- **Resources**: 1Gi memory, 1000m CPU (requests/limits)
- **Secrets**: Automatically injected from AWS Secrets Manager via External Secrets Operator
- **Mode**: Production (`start` command) - connects to LiveKit Cloud

**Note**: The agent connects outbound to LiveKit Cloud via WebSocket, so no Kubernetes Service/LoadBalancer is needed.

### Auto-Scaling Configuration

The agent uses **Horizontal Pod Autoscaler (HPA)** for automatic scaling:

- **Min replicas**: 1 (always at least 1 pod running)
- **Max replicas**: 10 (can scale up to 10 pods)
- **CPU target**: 70% utilization
- **Memory target**: 80% utilization
- **Scale up**: Fast (100% increase or +2 pods every 15 seconds)
- **Scale down**: Slow (50% decrease every 60 seconds, 5-minute stabilization window)

**Metrics Server**: Required for HPA to function. Install with:
```bash
helm repo add metrics-server https://kubernetes-sigs.github.io/metrics-server/
helm upgrade --install metrics-server metrics-server/metrics-server \
  --namespace kube-system \
  --set args="{--kubelet-insecure-tls}" \
  --wait
```

**Monitor HPA:**
```bash
# Check HPA status
kubectl get hpa livekit-agent -n apps

# View detailed HPA metrics
kubectl describe hpa livekit-agent -n apps

# View pod resource usage
kubectl top pods -n apps -l app=livekit-agent
```

## 📊 Monitoring and Scaling

### Check HPA Status

```bash
# View HPA current status
kubectl get hpa livekit-agent -n apps

# Detailed HPA information
kubectl describe hpa livekit-agent -n apps

# View current pod metrics
kubectl top pods -n apps -l app=livekit-agent
```

### HPA Behavior

- **Scale Up Triggers**: When CPU > 70% OR Memory > 80% (whichever is higher)
- **Scale Down Triggers**: When BOTH CPU < 70% AND Memory < 80% (with 5-minute stabilization)
- **Scaling Speed**: 
  - Up: Very fast (100% increase or +2 pods every 15s)
  - Down: Conservative (50% decrease every 60s)

### Adjusting HPA Settings

Edit `gitops/apps/backend/hpa.yaml` to change:
- Min/max replicas
- CPU/memory targets
- Scaling behavior (speed, stabilization windows)

After pushing changes, Argo CD will automatically sync the updated HPA configuration.

## 🐛 Troubleshooting

### HPA Not Scaling

1. **Check if Metrics Server is installed:**
   ```bash
   kubectl get deployment metrics-server -n kube-system
   kubectl top nodes  # Should work if metrics server is running
   ```

2. **Verify HPA is created:**
   ```bash
   kubectl get hpa -n apps
   kubectl describe hpa livekit-agent -n apps
   ```

3. **Check for HPA events:**
   ```bash
   kubectl describe hpa livekit-agent -n apps | grep -A 10 Events
   ```

4. **Verify pod resource requests are set:**
   ```bash
   kubectl get deployment livekit-agent -n apps -o jsonpath='{.spec.template.spec.containers[0].resources}'
   ```
   HPA requires resource requests to calculate utilization percentages.

### Argo CD Application Not Syncing

1. Check Argo CD UI for error messages
2. Verify Git repository is accessible (if private, configure credentials)
3. Check application status:
   ```bash
   kubectl get application root-app -n argocd -o yaml
   ```

### Agent Pods Not Starting (livekit-agent)

1. Check pod status:
   ```bash
   kubectl get pods -n apps -l app=livekit-agent
   kubectl describe pod <pod-name> -n apps
   kubectl logs <pod-name> -n apps
   ```

2. Verify image exists in ECR (repository name is `backend`):
   ```bash
   aws ecr describe-images --repository-name backend --region us-east-1
   ```

3. Check deployment:
   ```bash
   kubectl get deployment livekit-agent -n apps -o yaml
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

- **GitOps**: Prefer Git-driven deploys; avoid manual `kubectl apply` for app manifests.
- **Image updates**: CI (ci-backend.yaml) updates the agent image tag in `gitops/apps/backend/deployment.yaml`; manual tag edits may be overwritten on next deploy.
- **Terraform state**: Stored in S3 bucket `logicall-ai-terraform-state-<account-id>`.
- **Secrets**: No hardcoded credentials; use GitHub variables/secrets and AWS Secrets Manager with External Secrets Operator.

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
  --secret-string '{"LIVEKIT_URL":"...","LIVEKIT_API_KEY":"...","LIVEKIT_API_SECRET":"...","OPENAI_API_KEY":"...","ANTHROPIC_API_KEY":"..."}' \
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

See the **Secret Management** section above; a separate `SECRET_MANAGEMENT.md` may exist in the repo.

## 📚 Additional Resources

- [LiveKit Agents](https://docs.livekit.io/agents/) · [uv (Python)](https://docs.astral.sh/uv/)
- [Terraform AWS EKS Module](https://registry.terraform.io/modules/terraform-aws-modules/eks/aws/)
- [Argo CD](https://argo-cd.readthedocs.io/) · [External Secrets Operator](https://external-secrets.io/)
- [AWS Secrets Manager](https://docs.aws.amazon.com/secretsmanager/) · [DynamoDB](https://docs.aws.amazon.com/dynamodb/)
- [Kubernetes HPA](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/) · [Metrics Server](https://github.com/kubernetes-sigs/metrics-server)
- [AWS EKS Best Practices](https://aws.github.io/aws-eks-best-practices/)
- **In-repo:** [migrations/README.md](migrations/README.md) for DynamoDB profile setup

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

**Built with ❤️ using Terraform, GitHub Actions, Argo CD, and AWS EKS**

