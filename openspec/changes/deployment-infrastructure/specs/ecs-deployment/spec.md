## ADDED Requirements

### Requirement: ECS Fargate task definitions for all application services

ECS Fargate task definitions SHALL be provided for the backend, agent-service, and temporal services. Each task definition SHALL specify CPU, memory, port mappings, environment variable sources, log configuration, and health checks.

#### Scenario: Backend task definition

- **GIVEN** the backend task definition `deploy/ecs/backend-task-def.json`
- **WHEN** the task definition is inspected
- **THEN** the container has 512 CPU units and 1024 MB memory
- **AND** port 3000 is mapped
- **AND** environment variables `DATABASE_URL`, `REDIS_URL`, `TEMPORAL_ADDRESS` are sourced from SSM Parameter Store
- **AND** the log driver is `awslogs` with a CloudWatch log group
- **AND** the health check is `CMD curl -f http://localhost:3000/health`

#### Scenario: Agent service task definition

- **GIVEN** the agent-service task definition `deploy/ecs/agent-service-task-def.json`
- **WHEN** the task definition is inspected
- **THEN** the container has 1024 CPU units and 2048 MB memory
- **AND** no port mappings are defined (worker-only service)
- **AND** environment variables include `ANTHROPIC_API_KEY`, `GOOGLE_FACTCHECK_API_KEY`, `NEWSAPI_KEY` from SSM Parameter Store

#### Scenario: Temporal task definition

- **GIVEN** the temporal task definition `deploy/ecs/temporal-task-def.json`
- **WHEN** the task definition is inspected
- **THEN** the container has 1024 CPU units and 2048 MB memory
- **AND** port 7233 is mapped for gRPC

### Requirement: CloudFormation infrastructure stack

A CloudFormation template stack SHALL provision the complete AWS infrastructure: VPC with public/private subnets, ECS cluster with Fargate services, Aurora Serverless v2 cluster, ElastiCache Redis, ALB, S3 bucket, CloudFront distributions, and IAM roles.

#### Scenario: VPC with proper network isolation

- **GIVEN** the CloudFormation VPC template
- **WHEN** the stack is deployed
- **THEN** 2 public subnets and 2 private subnets are created across 2 availability zones
- **AND** ECS tasks run in private subnets
- **AND** the ALB runs in public subnets
- **AND** private subnets route internet traffic through a NAT Gateway

#### Scenario: Security groups enforce least privilege

- **GIVEN** the CloudFormation security groups
- **WHEN** the stack is deployed
- **THEN** the ALB SG allows inbound HTTPS (443) only
- **AND** the Backend SG allows inbound 3000 only from the ALB SG
- **AND** the Aurora SG allows inbound 5432 only from the Backend SG and Temporal SG
- **AND** the Redis SG allows inbound 6379 only from the Backend SG and Agent Service SG

#### Scenario: ECS services support scale-to-zero

- **GIVEN** the CloudFormation ECS service definitions
- **WHEN** the stack is deployed
- **THEN** the backend service has `desiredCount: 0` with auto-scaling min 0, max 3
- **AND** the agent-service has `desiredCount: 0` with auto-scaling min 0, max 2
- **AND** auto-scaling policies are defined for scaling up on ALB request count

#### Scenario: Aurora Serverless v2 with auto-pause

- **GIVEN** the CloudFormation Aurora cluster definition
- **WHEN** the stack is deployed
- **THEN** the cluster uses Aurora Serverless v2 with PostgreSQL 16
- **AND** minimum ACU is 0.5, maximum ACU is 4

#### Scenario: S3 bucket with lifecycle policy

- **GIVEN** the CloudFormation S3 bucket definition
- **WHEN** the stack is deployed
- **THEN** a lifecycle rule deletes objects in the `snapshots/` prefix after 3 days
- **AND** the bucket policy allows CloudFront OAI read access

### Requirement: Docker Compose hardened with health checks and resource limits

The Docker Compose file SHALL include health checks for all 8 services and resource limits (memory and CPU) for all services. All `depends_on` entries SHALL use `condition: service_healthy` where health checks are defined.

#### Scenario: All services have health checks

- **GIVEN** the `docker-compose.yml` file
- **WHEN** the configuration is inspected
- **THEN** all 8 services (frontend, backend, agent-service, temporal, temporal-ui, temporal-db, postgresql, redis) have health check definitions

#### Scenario: Resource limits are set

- **GIVEN** the `docker-compose.yml` file
- **WHEN** the configuration is inspected
- **THEN** each service has `deploy.resources.limits.memory` set
- **AND** each service has `deploy.resources.limits.cpus` set
