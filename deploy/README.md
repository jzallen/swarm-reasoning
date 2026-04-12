# Deployment

Three deployment targets: local development (Docker Compose), AWS production
(ECS Fargate + CloudFormation), and minikube demo (Helm chart).

## Local Development

### Prerequisites

- Docker and Docker Compose
- API keys: `ANTHROPIC_API_KEY`, `GOOGLE_FACTCHECK_API_KEY`, `NEWSAPI_KEY`

### Setup

```bash
cp .env.example .env
# Edit .env with your API keys

docker compose up
```

### Services

| Service       | URL                    |
|---------------|------------------------|
| Frontend      | http://localhost:5173   |
| Backend API   | http://localhost:3000   |
| Temporal UI   | http://localhost:8233   |

## AWS Production (ECS Fargate)

Architecture: Cloudflare edge proxy -> ALB -> ECS Fargate (private subnets),
Aurora Serverless v2, ElastiCache Redis, S3 + CloudFront for frontend/snapshots.

### Prerequisites

- AWS CLI configured with appropriate permissions
- ACM certificate for your domain (in us-east-1 for CloudFront, regional for ALB)
- Cloudflare account with domain configured

### 1. Deploy CloudFormation Stack

Upload nested templates to S3, then deploy the root stack:

```bash
# Upload templates
aws s3 sync deploy/ecs/cloudformation/ s3://YOUR-TEMPLATES-BUCKET/

# Deploy root stack
aws cloudformation deploy \
  --template-file deploy/ecs/cloudformation/main.yaml \
  --stack-name swarm-reasoning \
  --parameter-overrides \
    ACMCertificateArn=arn:aws:acm:... \
    DBMasterPassword=YOUR_SECURE_PASSWORD \
    BackendImageUri=ACCOUNT.dkr.ecr.REGION.amazonaws.com/swarm-reasoning/backend:latest \
    AgentServiceImageUri=ACCOUNT.dkr.ecr.REGION.amazonaws.com/swarm-reasoning/agent-service:latest \
    TemplatesBucket=YOUR-TEMPLATES-BUCKET \
  --capabilities CAPABILITY_NAMED_IAM
```

### 2. Populate SSM Parameters

Store API keys in SSM Parameter Store (SecureString):

```bash
aws ssm put-parameter --name /swarm-reasoning/anthropic-api-key \
  --type SecureString --value YOUR_KEY
aws ssm put-parameter --name /swarm-reasoning/google-factcheck-api-key \
  --type SecureString --value YOUR_KEY
aws ssm put-parameter --name /swarm-reasoning/newsapi-key \
  --type SecureString --value YOUR_KEY
```

### 3. Configure Cloudflare

Follow the setup steps in `deploy/cloudflare/README.md`. Key settings:
- SSL Full (Strict) mode
- CNAME records pointing to ALB and CloudFront
- Rate limiting on claim submission endpoint

### 4. CI/CD

GitHub Actions workflows handle automated deployment:
- **ci.yml**: Runs on every push — lint, test, build Docker images
- **deploy.yml**: Runs on push to main — deploy to AWS

Required GitHub Secrets:
- `AWS_ROLE_ARN`: IAM role ARN for OIDC federation
- `FRONTEND_BUCKET_NAME`: S3 bucket for frontend SPA
- `CLOUDFRONT_DISTRIBUTION_ID`: CloudFront distribution ID

### Infrastructure Components

| Component              | AWS Service              | Config File                            |
|------------------------|--------------------------|----------------------------------------|
| Networking (VPC)       | VPC, Subnets, NAT, SGs  | `ecs/cloudformation/vpc.yaml`          |
| Compute (ECS)          | ECS Fargate, ALB, ASG    | `ecs/cloudformation/ecs.yaml`          |
| Data Stores            | Aurora, ElastiCache, S3  | `ecs/cloudformation/data.yaml`         |
| CDN                    | CloudFront               | `ecs/cloudformation/cdn.yaml`          |
| IAM                    | Roles, OIDC, ECR         | `ecs/cloudformation/iam.yaml`          |
| Root Stack             | Nested stack orchestration | `ecs/cloudformation/main.yaml`       |
| Backend Task Def       | ECS Task Definition      | `ecs/backend-task-def.json`            |
| Agent Service Task Def | ECS Task Definition      | `ecs/agent-service-task-def.json`      |
| Temporal Task Def      | ECS Task Definition      | `ecs/temporal-task-def.json`           |

## Minikube Demo (Helm)

Kubernetes deployment for local demonstration using minikube.

### Prerequisites

- minikube with ingress addon enabled
- Helm 3
- Docker images built locally

### Setup

```bash
# Start minikube
minikube start
minikube addons enable ingress

# Build images in minikube's Docker daemon
eval $(minikube docker-env)
docker build -t swarm-reasoning/backend services/backend
docker build -t swarm-reasoning/frontend services/frontend
docker build -t swarm-reasoning/agent-service services/agent-service

# Install chart
helm install swarm-reasoning deploy/k8s/

# Add local DNS
echo "$(minikube ip) swarm-reasoning.local" | sudo tee -a /etc/hosts
```

### Access

Open http://swarm-reasoning.local in your browser.

### Customize

Edit `deploy/k8s/values.yaml` to change replica counts, resource limits, or
image tags. Update the secrets template with real API keys before deploying.

### Cleanup

```bash
helm uninstall swarm-reasoning
minikube stop
```
