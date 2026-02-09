```md
# EKS Fargate-only GitOps Starter (Terraform + GitHub Actions OIDC + Argo CD + Secrets Manager)

This repo provisions an Amazon EKS cluster that runs workloads on AWS Fargate only, then installs Argo CD and deploys apps via GitOps. It also shows how to use AWS Secrets Manager through External Secrets Operator (ESO).

Goals:
- Everything in Git
- No long-lived AWS keys, no IAM users for kubectl
- Rebuild quickly by re-applying Terraform and letting Argo CD reconcile apps

## What you will deploy

AWS:
- S3 bucket for Terraform state
- DynamoDB table for Terraform state locking
- IAM OIDC provider for GitHub Actions
- IAM role assumed by GitHub Actions (OIDC)
- VPC (public + private subnets, NAT)
- EKS control plane
- EKS Fargate profiles:
  - CoreDNS only in kube-system
  - apps namespace
- CoreDNS configured to run on Fargate
- (Optional) AWS Secrets Manager secret(s)

Kubernetes:
- Argo CD (installed by CI)
- Root Argo CD Application (points at `gitops/`)
- NGINX “hello world” app in `apps` namespace, exposed via Service type LoadBalancer
- External Secrets Operator and example ExternalSecret (optional)

## Repo layout

```

.
├── infra
│   ├── bootstrap
│   │   ├── main.tf
│   │   ├── variables.tf
│   │   └── outputs.tf
│   └── eks
│       ├── main.tf
│       ├── variables.tf
│       └── outputs.tf
├── gitops
│   ├── argocd
│   │   └── root-app.yaml
│   └── apps
│       ├── nginx-hello
│       │   ├── namespace.yaml
│       │   ├── deployment.yaml
│       │   └── service.yaml
│       └── external-secrets
│           ├── install.yaml (or helm values if you prefer Helm)
│           ├── secretstore.yaml
│           └── externalsecret.yaml
└── .github
└── workflows
└── deploy.yml

````

## Prerequisites

Accounts and tools:
- AWS account with permissions to create IAM, VPC, EKS, S3, DynamoDB
- GitHub repo for this project

One-time local or CloudShell tools (only needed for `infra/bootstrap`):
- Terraform
- AWS CLI

After bootstrap, GitHub Actions runs Terraform and kubectl/helm in a short-lived runner.

## Step 1: Configure your project variables

Decide:
- AWS region (example: `us-west-2`)
- Cluster name (example: `eks-fargate-only`)
- GitHub org and repo name (example: `my-org/my-repo`)
- Branch to allow in OIDC trust (example: `main`)

You will set these in:
- `infra/bootstrap/variables.tf` or `terraform.tfvars`
- `infra/eks/variables.tf` or `terraform.tfvars`

## Step 2: Run bootstrap (one time)

Bootstrap creates:
- Terraform state bucket and lock table
- GitHub Actions OIDC provider
- IAM role for GitHub Actions

From `infra/bootstrap`:

```bash
terraform init
terraform apply
````

Take note of outputs:

* state bucket name
* lock table name
* GitHub Actions role ARN

## Step 3: Configure Terraform backend for the EKS stack

In `infra/eks`, configure remote backend to use the S3 bucket and DynamoDB table created by bootstrap.

Example `backend.tf` (create this file in `infra/eks`):

```hcl
terraform {
  backend "s3" {
    bucket         = "REPLACE_WITH_STATE_BUCKET"
    key            = "eks/terraform.tfstate"
    region         = "REPLACE_WITH_REGION"
    dynamodb_table = "REPLACE_WITH_LOCK_TABLE"
    encrypt        = true
  }
}
```

Then:

```bash
cd infra/eks
terraform init
```

Commit `backend.tf` after you fill it in.

## Step 4: Add GitHub Actions workflow

Create `.github/workflows/deploy.yml` that does:

* Assume AWS role via OIDC
* Terraform apply for `infra/eks`
* Install Argo CD
* Apply Argo root app

Important GitHub Actions permissions:

* `id-token: write`
* `contents: read`

You will need these secrets or variables in GitHub:

* No AWS keys needed
* Provide:

  * `AWS_REGION`
  * `AWS_ROLE_ARN` (from bootstrap output)
  * `CLUSTER_NAME` (same as Terraform)

## Step 5: Push to GitHub and run the workflow

Push your repo to GitHub.
Run the workflow (or merge to main if your workflow triggers on push).

Expected outcome:

* EKS cluster exists
* Fargate profiles exist
* CoreDNS is on Fargate
* Argo CD is installed
* Root app is applied, Argo starts reconciling `gitops/`

## Step 6: Deploy NGINX “hello world”

Argo will apply the manifests in `gitops/apps/nginx-hello`.

The minimum files:

`gitops/apps/nginx-hello/namespace.yaml`

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: apps
```

`gitops/apps/nginx-hello/deployment.yaml`

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-hello
  namespace: apps
spec:
  replicas: 1
  selector:
    matchLabels:
      app: nginx-hello
  template:
    metadata:
      labels:
        app: nginx-hello
    spec:
      containers:
        - name: nginx
          image: nginx:stable
          ports:
            - containerPort: 80
          command: ["/bin/sh", "-c"]
          args:
            - |
              echo 'hello world' > /usr/share/nginx/html/index.html &&
              nginx -g 'daemon off;'
```

`gitops/apps/nginx-hello/service.yaml`

```yaml
apiVersion: v1
kind: Service
metadata:
  name: nginx-hello
  namespace: apps
spec:
  type: LoadBalancer
  selector:
    app: nginx-hello
  ports:
    - port: 80
      targetPort: 80
```

When Argo syncs, an external endpoint will appear. You can see it in AWS console or by running:

```bash
kubectl get svc -n apps
```

If you do not want to run kubectl locally, view it via AWS console:

* EKS cluster -> Resources -> Services and ingress
* Or the EC2 Load Balancers page for the created load balancer

## Step 7: Use AWS Secrets Manager with External Secrets Operator (optional)

You can manage the AWS secret in Terraform:

* `aws_secretsmanager_secret`
* `aws_secretsmanager_secret_version`

Then install ESO via GitOps and configure:

* `SecretStore` that authenticates using IRSA
* `ExternalSecret` that reads a secret from Secrets Manager and writes a Kubernetes Secret

High level pieces you need:

1. Terraform creates:

   * Secrets Manager secret
   * IAM policy for reading that secret ARN
   * IAM role for ESO service account (IRSA)
2. GitOps applies:

   * ESO installation
   * ServiceAccount annotated to use the IRSA role
   * SecretStore and ExternalSecret resources

After ESO syncs, your app can use the Kubernetes Secret as env vars or mounted volume.

## How to rebuild quickly

To recreate the cluster:

* Terraform apply from CI creates or updates AWS infra
* Argo CD reconciles Kubernetes resources from Git

If you destroy and recreate:

* `terraform destroy` for `infra/eks`
* then `terraform apply` again
* Argo CD will be reinstalled by CI, then it will resync apps

Do not destroy `infra/bootstrap` unless you want to rebuild the CI trust and Terraform state.

## Cursor tips to work efficiently

Suggested prompts to Cursor:

* “Create Terraform bootstrap stack for S3 backend, DynamoDB lock, GitHub OIDC provider, and an IAM role restricted to this repo and branch.”
* “Create EKS Fargate-only Terraform stack with CoreDNS on Fargate and an apps namespace Fargate profile.”
* “Generate GitHub Actions workflow using aws-actions/configure-aws-credentials with OIDC and then run terraform apply and install Argo CD with Helm.”
* “Create Argo CD root application that points to gitops/ and enables auto-sync.”

Suggested workflow:

1. Use Cursor to generate `infra/bootstrap`
2. Apply bootstrap once
3. Use Cursor to generate `infra/eks`
4. Add workflow and GitOps manifests
5. Push and let CI do the rest

## Troubleshooting

CoreDNS pending:

* Ensure your Fargate profile selector matches CoreDNS labels in kube-system.
* Ensure CoreDNS add-on is configured to run on Fargate.

Pods not scheduled:

* Ensure the namespace matches the Fargate profile selector, for example `apps`.

No external endpoint:

* Service type must be `LoadBalancer`
* It can take a few minutes to provision
* Check AWS Load Balancers console

Argo CD cannot pull repo:

* If repo is private, you must configure Argo repo credentials or use GitHub App/token method.