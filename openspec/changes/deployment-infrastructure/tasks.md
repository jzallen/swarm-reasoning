## 1. Docker Compose Hardening

- [x] 1.1 Add health checks to `agent-service`, `temporal`, `temporal-ui`, and `frontend`
- [x] 1.2 Update all `depends_on` entries to use `condition: service_healthy`
- [x] 1.3 Add memory limits to all 8 services (frontend: 512M, backend: 1G, agent-service: 2G, temporal: 1G, temporal-ui: 512M, temporal-db: 512M, postgresql: 512M, redis: 256M)
- [x] 1.4 Add CPU limits to all 8 services
- [x] 1.5 Add `logging` configuration with `json-file` driver and max-size/max-file limits

## 2. Environment Variable Management

- [x] 2.1 Create `.env.example` at project root with all required variables: `ANTHROPIC_API_KEY`, `GOOGLE_FACTCHECK_API_KEY`, `NEWSAPI_KEY`
- [x] 2.2 Document optional variables with defaults: `DATABASE_URL`, `REDIS_URL`, `TEMPORAL_ADDRESS`, `SNAPSHOT_STORE`, `S3_BUCKET_NAME`, `AWS_REGION`, `CLOUDFRONT_DOMAIN`, `NODE_ENV`
- [x] 2.3 Add `.env` to `.gitignore` if not present

## 3. Dockerfiles

- [x] 3.1 Create `services/backend/Dockerfile`: multi-stage build (deps -> build TS -> node:20-slim production)
- [x] 3.2 Create `services/frontend/Dockerfile`: multi-stage build (deps -> Vite build -> nginx:alpine serving static)
- [x] 3.3 Verify `services/agent-service/Dockerfile` (Python 3.11, deps, Temporal workers)
- [x] 3.4 Add `.dockerignore` to each service; use specific version tags for base images

## 4. ECS Task Definitions

- [x] 4.1 Create `deploy/ecs/backend-task-def.json`: 512 CPU, 1024 MB, port 3000, env from SSM, awslogs, health check
- [x] 4.2 Create `deploy/ecs/agent-service-task-def.json`: 1024 CPU, 2048 MB, no port mapping, env from SSM
- [x] 4.3 Create `deploy/ecs/temporal-task-def.json`: 1024 CPU, 2048 MB, port 7233, env for DB connection

## 5. CloudFormation - Networking

- [x] 5.1 Create `deploy/ecs/cloudformation/vpc.yaml`: VPC with 2 public + 2 private subnets across 2 AZs
- [x] 5.2 Define IGW, NAT Gateway (single AZ), route tables
- [x] 5.3 Define security groups: ALB (443 inbound), Backend (3000 from ALB), Agent Service (outbound only), Temporal (7233 from Backend+Agent), Aurora (5432 from Backend+Temporal), Redis (6379 from Backend+Agent)

## 6. CloudFormation - Compute

- [x] 6.1 Create `deploy/ecs/cloudformation/ecs.yaml`: ECS cluster with Fargate capacity providers
- [x] 6.2 Backend ECS service: desired 0, min 0, max 3, scale on ALB request count
- [x] 6.3 Agent Service ECS service: desired 0, min 0, max 2
- [x] 6.4 Temporal ECS service: desired 1 (always on)
- [x] 6.5 ALB with HTTPS listener (ACM cert), target group for backend, listener rules for `/sessions/*`, `/health`
- [x] 6.6 Application Auto Scaling policies for backend and agent-service

## 7. CloudFormation - Data Stores

- [x] 7.1 Create `deploy/ecs/cloudformation/data.yaml`: Aurora Serverless v2 (PostgreSQL 16, min 0.5 ACU, max 4 ACU)
- [x] 7.2 ElastiCache Redis: single node `cache.t4g.micro`, Redis 7, private subnet
- [x] 7.3 S3 bucket for snapshots: lifecycle rule (delete after 3 days), bucket policy for CloudFront OAI
- [x] 7.4 SSM Parameter Store entries for DB URL, Redis URL, API keys

## 8. CloudFormation - CDN and IAM

- [x] 8.1 Create `deploy/ecs/cloudformation/cdn.yaml`: CloudFront for frontend SPA (S3 origin, SPA error handling) and snapshots
- [x] 8.2 CloudFront OAI for S3 access; cache behaviors for assets vs snapshots
- [x] 8.3 Create `deploy/ecs/cloudformation/iam.yaml`: ECS execution role (ECR pull, SSM read, CloudWatch logs), task roles (backend: S3 write; agent-service: Redis/Temporal)
- [x] 8.4 Create `deploy/ecs/cloudformation/main.yaml`: root template importing nested stacks with parameters and outputs

## 9. Cloudflare Configuration

- [x] 9.1 Create `deploy/cloudflare/dns-records.json`: CNAME to ALB/CloudFront, proxy mode enabled
- [x] 9.2 Create `deploy/cloudflare/ssl-settings.json`: full_strict, min TLS 1.2, HSTS enabled
- [x] 9.3 Create `deploy/cloudflare/rate-limit-rules.json`: POST `/sessions/*/claims` at 10 req/min/IP
- [x] 9.4 Create `deploy/cloudflare/cache-rules.json`: cache static assets, bypass API and SSE
- [x] 9.5 Create `deploy/cloudflare/README.md` with manual setup steps

## 10. Helm Chart - Structure and Config

- [x] 10.1 Create `deploy/k8s/Chart.yaml`, `values.yaml`, `.helmignore`, `templates/_helpers.tpl`
- [x] 10.2 Parameterize image tags, replica counts, resource limits, and env vars in `values.yaml`

## 11. Helm Chart - Application Services

- [x] 11.1 Create backend templates: deployment (health probe, resource limits, env from ConfigMap/Secret), service (ClusterIP:3000), ingress (`/sessions/*`, `/health`)
- [x] 11.2 Create agent-service templates: deployment (resource limits, env from ConfigMap/Secret), configmap
- [x] 11.3 Create frontend templates: deployment (nginx), service (ClusterIP:80), ingress (`/`)

## 12. Helm Chart - Data Services

- [x] 12.1 Create postgresql: StatefulSet with PVC, service (ClusterIP:5432)
- [x] 12.2 Create redis: Deployment (appendonly), service (ClusterIP:6379)
- [x] 12.3 Create temporal: Deployment (auto-setup image), service (ClusterIP:7233)
- [x] 12.4 Create temporal-ui: Deployment, service (ClusterIP:8233)
- [x] 12.5 Create temporal-db: StatefulSet with PVC, service (ClusterIP:5432)
- [x] 12.6 Create secrets template for API keys

## 13. GitHub Actions - CI Workflow

- [x] 13.1 Create `.github/workflows/ci.yml`: trigger on push (all branches) and PR to main
- [x] 13.2 Jobs: `lint-and-test-backend` (Node 20, ESLint, Prettier, Jest), `lint-and-test-frontend` (Node 20, ESLint, Prettier, Vitest), `lint-and-test-agent-service` (Python 3.11, Ruff, pytest)
- [x] 13.3 Job: `build-images` -- build Docker images for all three services (no push)
- [x] 13.4 Configure npm and pip caching for faster builds

## 14. GitHub Actions - Deploy Workflow

- [x] 14.1 Create `.github/workflows/deploy.yml`: trigger on push to main
- [x] 14.2 Job: `deploy-frontend` -- Vite build, S3 sync, CloudFront invalidation
- [x] 14.3 Job: `deploy-backend` -- Docker build, push to ECR, update ECS task definition
- [x] 14.4 Job: `deploy-agent-service` -- Docker build, push to ECR, update ECS task definition
- [x] 14.5 Configure AWS credentials via OIDC; add ECR repo definitions to CloudFormation

## 15. Documentation

- [x] 15.1 Create `deploy/README.md`: local dev setup, AWS deployment, minikube demo instructions
