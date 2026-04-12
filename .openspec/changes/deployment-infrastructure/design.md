## Context

ADR-0020 specifies Cloudflare (free tier) for edge proxy and AWS ECS Fargate for serverless container hosting. The existing Docker Compose file defines 8 services but lacks health checks on some services, resource limits, and proper health-condition dependencies. Production deployment requires ECS task definitions, CloudFormation for AWS infrastructure, Cloudflare DNS/SSL/rate-limiting configuration, and a CI/CD pipeline. A Helm chart for minikube demonstrates Kubernetes knowledge.

Key constraints from architecture docs:
- ADR-0014: Three services -- frontend (React/Vite), backend (NestJS), agent-service (Python/LangChain)
- ADR-0020: ECS Fargate + Cloudflare free tier; minikube Helm chart for portfolio
- Docker Compose: 8 services (frontend, backend, agent-service, temporal, temporal-ui, temporal-db, postgresql, redis)
- Frontend: S3 + CloudFront in production
- Backend + Agent Service: ECS Fargate with scale-to-zero
- PostgreSQL: Aurora Serverless v2 in production
- Redis: ElastiCache (t4g.micro) in production
- Temporal: self-hosted on ECS Fargate
- Cloudflare: DNS proxy, SSL full (strict), rate limiting (10 submissions/min/IP)
- Required env vars: ANTHROPIC_API_KEY, GOOGLE_FACTCHECK_API_KEY, NEWSAPI_KEY

## Goals / Non-Goals

**Goals:**
- Harden Docker Compose with health checks, resource limits, and proper dependency ordering
- Define ECS Fargate task definitions for backend, agent-service, and temporal
- Create CloudFormation templates for the full AWS infrastructure stack
- Document Cloudflare configuration as reproducible configuration files
- Create a Helm chart for minikube demonstration
- Create a GitHub Actions CI/CD pipeline
- Provide `.env.example` with all required environment variables

**Non-Goals:**
- Multi-region deployment
- Blue/green or canary deployment strategies (rolling update is sufficient)
- Terraform (CloudFormation is chosen for AWS-native consistency)
- Production Temporal Cloud (self-hosted Temporal on ECS is the target)
- Kubernetes in production (ECS is the production target; Helm chart is for portfolio demo only)
- Cost optimization beyond scale-to-zero (this is a portfolio project)

## Decisions

### 1. CloudFormation over Terraform

CloudFormation is the native AWS IaC tool. Since the production target is exclusively AWS (ADR-0020), CloudFormation avoids the Terraform state management overhead and provider version pinning. All infrastructure is defined in a single CloudFormation template with nested stacks for logical grouping.

**Alternative considered:** Terraform. Rejected -- adds a third-party dependency for a single-cloud deployment; CloudFormation is native and free.

### 2. Single VPC with public and private subnets

The VPC has 2 public subnets (ALB, NAT Gateway) and 2 private subnets (ECS tasks, Aurora, ElastiCache) across 2 AZs. ECS tasks run in private subnets with internet access via NAT Gateway. The ALB in public subnets terminates HTTPS (from Cloudflare) and routes to ECS tasks.

### 3. ECS Fargate with minimum desired count of 0

Backend and agent-service ECS services have `desiredCount: 0` with Application Auto Scaling. A CloudWatch alarm on ALB request count triggers scale-up from 0 to 1 (and beyond based on CPU utilization). This achieves the scale-to-zero goal from ADR-0020. Cold start latency (~30s for backend, ~60s for agent-service) is acceptable for a portfolio project.

**Alternative considered:** Always-on minimum of 1 task. Rejected -- unnecessary cost for a portfolio project with sporadic traffic.

### 4. Cloudflare SSL Full (Strict) with ALB HTTPS

Cloudflare terminates the client-facing SSL connection. Between Cloudflare and the ALB, traffic uses HTTPS with an ACM certificate. The ALB terminates this connection and forwards HTTP to ECS tasks. This is the "Full (Strict)" SSL mode in Cloudflare, preventing MITM between Cloudflare and origin.

### 5. Rate limiting via Cloudflare WAF rule

A single Cloudflare rate limiting rule caps `POST /sessions/*/claims` to 10 requests per minute per IP. This prevents abuse of the claim submission endpoint (which triggers expensive LLM processing). The rule is documented as a Cloudflare API call or dashboard configuration in `deploy/cloudflare/rate-limit.json`.

### 6. Helm chart structure mirrors Docker Compose

The Helm chart under `deploy/k8s/` defines Kubernetes resources for all 8 services, mirroring the Docker Compose topology. Each service gets a Deployment, Service, and ConfigMap. The backend gets an Ingress resource. Values.yaml parameterizes image tags, replica counts, and environment variables.

**Alternative considered:** Kustomize. Rejected -- Helm is more widely recognized in the industry and better demonstrates templating skills.

### 7. GitHub Actions with two workflows

- **ci.yml**: Triggered on push to any branch. Runs linting, unit tests, and type checking for both TypeScript (NestJS + frontend) and Python (agent-service). Builds Docker images to verify Dockerfiles are valid.
- **deploy.yml**: Triggered on push to `main`. Builds and pushes Docker images to ECR, syncs frontend build to S3, and updates ECS services to use the new task definition revision.

### 8. Docker Compose hardening

Add to existing `docker-compose.yml`:
- Health checks for `agent-service` and `temporal` (frontend and backend already have or can use curl-based checks)
- Memory limits via `deploy.resources.limits.memory` for all services
- CPU limits via `deploy.resources.limits.cpus` for all services
- All `depends_on` entries use `condition: service_healthy` where a health check is defined

## Risks / Trade-offs

- **[Cold start latency]** Scale-to-zero means first request after idle incurs ~30-60s cold start. Mitigation: acceptable for portfolio project; Cloudflare can show a "loading" page during cold start using a Worker.
- **[Self-hosted Temporal on Fargate]** Temporal Server requires its own PostgreSQL database and careful version management. Mitigation: use the `temporalio/auto-setup` image for automatic schema migration; monitor via Temporal UI.
- **[CloudFormation stack complexity]** A single template with VPC, ECS, Aurora, ElastiCache, S3, CloudFront, IAM is large. Mitigation: use nested stacks for logical grouping (networking, compute, data, CDN).
- **[Cloudflare free tier limits]** Rate limiting on the free tier is limited to 1 rule. Mitigation: one rule is sufficient (POST /sessions/*/claims); other endpoints are read-only and low-risk.
- **[Helm chart maintenance]** The Helm chart is for demonstration only and may drift from Docker Compose over time. Mitigation: document clearly that the Helm chart is a portfolio artifact, not a production deployment target.
