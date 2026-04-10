---
status: accepted
date: 2026-04-10
deciders: []
---

# ADR-0020: Cloudflare Edge Proxy with AWS ECS Fargate Deployment

## Context and Problem Statement

The system needs a production deployment target that is cost-effective for a portfolio project with sporadic traffic. It must handle DDoS protection, SSL termination, and rate limiting while supporting scale-to-zero where possible to minimize idle costs.

## Decision Drivers

- Cost-effective for a portfolio project: pay only for what is used
- Scale-to-zero for sporadic traffic patterns
- DDoS protection without additional cost
- Demonstrate both ECS and Kubernetes knowledge in the repository

## Considered Options

1. **EKS (Kubernetes on AWS)** -- Full managed Kubernetes but requires a persistent control plane at approximately $73/month minimum regardless of traffic. Production-grade but expensive for a portfolio project with sporadic usage.
2. **ECS Fargate** -- Serverless containers with native scale-to-zero. No cluster management, pay-per-second billing. AWS-specific but well-suited for cost-sensitive workloads.
3. **Single EC2 instance** -- Cheapest fixed cost but no auto-scaling, single point of failure, and requires manual OS patching and container runtime management.

## Decision Outcome

Chosen option: "ECS Fargate + Cloudflare", because ECS scales to zero natively, Cloudflare free tier covers edge security, and a minikube Helm chart in the repository demonstrates Kubernetes skills without ongoing cost.

**Edge layer -- Cloudflare (free tier)**

- DNS proxy providing DDoS protection and bot mitigation
- SSL termination at the edge
- Rate limiting (1 rule: cap claim submissions per IP)
- No additional cost for the free tier

**Application layer -- AWS**

- Frontend: S3 + CloudFront (static SPA and verdict snapshots)
- Backend API: ECS Fargate (scales to zero tasks when idle)
- Agent Service: ECS Fargate (scales to zero tasks when idle)
- PostgreSQL: Aurora Serverless v2 (scales to near-zero ACUs)
- Redis: ElastiCache (single node, t4g.micro for dev/portfolio)
- Temporal Server: ECS Fargate

**Local development** uses Docker Compose (unchanged from existing setup).

A Helm chart and minikube configuration is included in the repository under `deploy/k8s/` to demonstrate Kubernetes knowledge without requiring a persistent cluster or ongoing cost.

### Consequences

- Good, because near-zero cost when idle -- ECS Fargate charges only for running tasks, Aurora Serverless v2 scales down during inactivity
- Good, because Cloudflare free tier absorbs DDoS and bot traffic without cost
- Good, because no cluster management overhead compared to EKS or self-managed Kubernetes
- Good, because the Helm chart in `deploy/k8s/` demonstrates Kubernetes proficiency for portfolio purposes
- Bad, because ECS is AWS-specific with no multi-cloud portability
- Bad, because self-hosting Temporal Server on Fargate adds operational complexity (health checks, schema migrations, version upgrades)
- Neutral, because local development uses Docker Compose regardless of the production deployment target

## More Information

- Deployment artifacts: `deploy/ecs/` (ECS task definitions, CloudFormation templates) and `deploy/k8s/` (Helm chart for minikube demo)
- ADR-0014: Three-Service Architecture (the three services deployed to Fargate)
- ADR-0019: Static HTML Verdict Snapshots (S3 + CloudFront hosting for verdict pages)
