## Why

The system runs locally via Docker Compose but has no production deployment target, no CI/CD pipeline, and no edge security configuration. ADR-0020 specifies Cloudflare for edge proxy (DDoS, SSL, rate limiting) and AWS ECS Fargate for serverless container hosting with scale-to-zero. A Helm chart for minikube demonstrates Kubernetes knowledge. This slice delivers the full deployment stack: Docker Compose hardening, ECS task definitions, CloudFormation infrastructure, Cloudflare configuration, Helm chart, CI/CD pipeline, and environment variable management.

## What Changes

- Harden Docker Compose: add health checks to all services, resource limits (memory/CPU), proper dependency ordering with health conditions, `.env.example` with all required variables
- Create ECS Fargate task definitions for: backend, agent-service, temporal
- Create CloudFormation templates for: VPC with public/private subnets, Aurora Serverless v2 cluster, ElastiCache Redis (t4g.micro), Application Load Balancer, ECS cluster + services, S3 bucket for snapshots with lifecycle policy, CloudFront distribution for frontend + snapshots, IAM roles and security groups
- Document Cloudflare DNS configuration: proxy mode, SSL full (strict), rate limiting rule (10 claim submissions per minute per IP), caching rules for static assets
- Create Helm chart for minikube: deployment.yaml, service.yaml, ingress.yaml, configmap.yaml for backend, agent-service, and temporal; values.yaml with environment-specific overrides
- Create GitHub Actions CI/CD pipeline: build (lint + test) -> Docker image build -> push to ECR -> deploy to ECS
- Create `.env.example` documenting all required and optional environment variables

## Capabilities

### New Capabilities

- `ecs-deployment`: ECS Fargate task definitions, service definitions, and CloudFormation templates for the full AWS infrastructure stack. Includes VPC networking, ALB routing, Aurora Serverless v2, ElastiCache, S3, CloudFront, IAM, and security groups.
- `cloudflare-configuration`: DNS proxy configuration, SSL settings, rate limiting rules, and caching configuration for Cloudflare free tier. Documents the setup as infrastructure-as-code style configuration files.
- `k8s-helm-chart`: Helm chart under `deploy/k8s/` for minikube demonstration. Includes deployments, services, ingress, and configmaps for all three application services plus Temporal and data stores.
- `ci-cd-pipeline`: GitHub Actions workflow with build, test, Docker image build, ECR push, and ECS deploy stages. Separate workflows for frontend (S3 sync) and backend/agent-service (ECS rolling update).

### Modified Capabilities

- `docker-compose` (existing): Enhanced with health checks for all services, resource limits, and dependency ordering using health conditions instead of `service_started`.

## Impact

- **New files**: ECS task definitions (`deploy/ecs/`), CloudFormation templates (`deploy/ecs/`), Cloudflare config docs (`deploy/cloudflare/`), Helm chart (`deploy/k8s/`), GitHub Actions workflows (`.github/workflows/`), `.env.example`
- **Modified files**: `docs/infrastructure/docker-compose.yml` (add health checks, resource limits)
- **No new containers in dev**: All deployment artifacts target production or minikube; local dev remains unchanged
