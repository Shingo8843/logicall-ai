# Backend-only GitOps on EKS using GitHub Actions, Terraform, and Argo CD (Python)
https://medium.com/%40neamulkabiremon/build-a-real-world-devops-pipeline-with-github-actions-terraform-eks-and-argo-cd-step-by-step-c568f1efd29e
https://github.com/neamulkabiremon/ultimate-devops-project-demo
This repository follows the same architecture and workflow described in the Medium article:

> *Build a real-world DevOps pipeline with GitHub Actions, Terraform, EKS, and Argo CD*

The only differences are:

* Python backend instead of Node.js
* Backend-only service (no frontend)
* Same CI-driven GitOps pattern where **CI updates manifests and Argo CD syncs**

---

## Architecture (same as the Medium article)

1. **Terraform** provisions the EKS cluster
2. **GitHub Actions (CI)**:

   * builds a Docker image
   * pushes it to Amazon ECR
   * updates the Kubernetes manifest with the new image tag
3. **Argo CD**:

   * watches the Git repository
   * syncs Kubernetes manifests to the cluster automatically

Git is the single source of truth.

---

## Repository structure

```
.
├── app/                         # Python backend source
│   └── main.py
├── Dockerfile
├── requirements.txt
│
├── infra/
│   └── eks/                     # Terraform (same role as Medium article)
│
├── gitops/
│   ├── argocd/
│   │   └── root-app.yaml        # Argo CD Application
│   └── apps/
│       └── backend/
│           ├── namespace.yaml
│           ├── deployment.yaml
│           └── service.yaml
│
└── .github/
    └── workflows/
        ├── deploy-eks.yaml      # EKS + Argo CD bootstrap (your existing one)
        └── ci-backend.yaml      # Build, push, update manifest
```

This mirrors the Medium article’s “infra + app + gitops” separation.

---

## Prerequisites

Before starting, make sure you have:

* AWS account
* IAM role for GitHub OIDC (same as Medium article)
* GitHub repository (public or private)
* Terraform >= 1.6
* AWS CLI configured locally (for first run only)

---

## Step 1: Provision EKS (same as Medium article)

Terraform lives in:

```
infra/eks
```

Run locally once if desired:

```bash
cd infra/eks
terraform init
terraform apply
```

Or let GitHub Actions run the **deploy-eks.yaml** workflow.

This workflow:

* creates the EKS cluster
* installs Argo CD
* applies `gitops/argocd/root-app.yaml`

No application code is deployed yet.

---

## Step 2: Python backend (minimal)

`app/main.py`

```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/health")
def health():
    return {"ok": True}
```

`requirements.txt`

```txt
fastapi
uvicorn[standard]
```

`Dockerfile`

```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host=0.0.0.0", "--port=8000"]
```

This directly replaces the Node app in the Medium tutorial.

---

## Step 3: Kubernetes manifests (GitOps source of truth)

`gitops/apps/backend/deployment.yaml`

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: backend
  namespace: apps
spec:
  replicas: 1
  selector:
    matchLabels:
      app: backend
  template:
    metadata:
      labels:
        app: backend
    spec:
      containers:
        - name: backend
          image: YOUR_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/backend:REPLACE_ME
          ports:
            - containerPort: 8000
```

`gitops/apps/backend/service.yaml`

```yaml
apiVersion: v1
kind: Service
metadata:
  name: backend
  namespace: apps
spec:
  selector:
    app: backend
  ports:
    - port: 80
      targetPort: 8000
  type: ClusterIP
```

`gitops/apps/backend/namespace.yaml`

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: apps
```

This is identical in spirit to the Medium article’s manifests.

---

## Step 4: Argo CD Application (same model as Medium)

`gitops/argocd/root-app.yaml`

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: backend
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/YOUR_ORG/YOUR_REPO.git
    targetRevision: main
    path: gitops/apps/backend
  destination:
    server: https://kubernetes.default.svc
    namespace: apps
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

This is the same “CI commits → Argo CD syncs” pattern used in the Medium article.

---

## Step 5: CI pipeline (standard GitOps)

`.github/workflows/ci-backend.yaml`

What it does:

1. Build Python image
2. Push to Amazon ECR
3. Update `deployment.yaml` image tag
4. Commit the change back to Git

This is the **standard CI-driven GitOps pattern** and matches the article’s intent exactly.

Once this runs:

* Git changes
* Argo CD detects the change
* Backend is deployed

---

## How deployments work (important)

* **Do not kubectl apply app manifests manually**
* **Do not change image tags by hand**

Deployment flow:

```
git push → GitHub Actions → Git commit → Argo CD sync
```

Rollback:

```bash
git revert <commit>
```

---

## Common first-run checklist

Before triggering CI:

* ECR repository `backend` exists
* Argo CD can access the Git repository
* `repoURL` in `root-app.yaml` is correct
* AWS_REGION matches ECR and EKS

---

## Why this matches the Medium article closely

* Terraform still owns EKS
* GitHub Actions still does build + deploy
* Argo CD still reconciles Git state
* No extra controllers or patterns added
* Only language changed (Node → Python)

---

If you want, next I can:

* diff this against the Medium repo line-by-line
* tighten it further to avoid any Argo CD edge cases
* add an optional Ingress later without changing the core flow
