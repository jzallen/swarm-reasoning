## ADDED Requirements

### Requirement: CI workflow runs linting and tests on every push

A GitHub Actions workflow (`ci.yml`) SHALL run on push to all branches and on pull requests to `main`. The workflow SHALL lint and test both TypeScript services (frontend and backend) and the Python agent-service. Docker images SHALL be built to validate Dockerfiles.

#### Scenario: CI triggers on push

- **GIVEN** the `.github/workflows/ci.yml` workflow
- **WHEN** a commit is pushed to any branch
- **THEN** the CI workflow is triggered

#### Scenario: Backend lint and test job

- **GIVEN** the CI workflow is running
- **WHEN** the `lint-and-test-backend` job executes
- **THEN** Node.js 20 is set up
- **AND** `npm ci` installs dependencies
- **AND** ESLint runs without errors
- **AND** Prettier check runs without formatting issues
- **AND** Jest test suite passes

#### Scenario: Frontend lint and test job

- **GIVEN** the CI workflow is running
- **WHEN** the `lint-and-test-frontend` job executes
- **THEN** Node.js 20 is set up
- **AND** ESLint and Prettier checks pass
- **AND** Vitest test suite passes

#### Scenario: Agent service lint and test job

- **GIVEN** the CI workflow is running
- **WHEN** the `lint-and-test-agent-service` job executes
- **THEN** Python 3.11 is set up
- **AND** Ruff linter runs without errors
- **AND** pytest test suite passes

#### Scenario: Docker image build validation

- **GIVEN** the CI workflow is running
- **WHEN** the `build-images` job executes
- **THEN** Docker images are built for backend, frontend, and agent-service
- **AND** all Dockerfiles build successfully
- **AND** no images are pushed to any registry

### Requirement: Deploy workflow pushes to ECR and updates ECS on merge to main

A GitHub Actions workflow (`deploy.yml`) SHALL run on push to `main`. It SHALL build Docker images, push to ECR, sync the frontend build to S3, and update ECS services with new task definition revisions.

#### Scenario: Deploy triggers on main push

- **GIVEN** the `.github/workflows/deploy.yml` workflow
- **WHEN** a commit is pushed to the `main` branch
- **THEN** the deploy workflow is triggered

#### Scenario: Frontend deployment to S3

- **GIVEN** the deploy workflow is running
- **WHEN** the `deploy-frontend` job executes
- **THEN** Vite builds the frontend SPA
- **AND** the build output is synced to the S3 bucket
- **AND** the CloudFront distribution cache is invalidated

#### Scenario: Backend deployment to ECS

- **GIVEN** the deploy workflow is running
- **WHEN** the `deploy-backend` job executes
- **THEN** the Docker image is built and pushed to the ECR repository `swarm-reasoning/backend`
- **AND** a new ECS task definition revision is registered with the new image tag
- **AND** the ECS service is updated to use the new task definition

#### Scenario: Agent service deployment to ECS

- **GIVEN** the deploy workflow is running
- **WHEN** the `deploy-agent-service` job executes
- **THEN** the Docker image is built and pushed to the ECR repository `swarm-reasoning/agent-service`
- **AND** the ECS service is updated with the new task definition revision

#### Scenario: AWS credentials via OIDC

- **GIVEN** the deploy workflow
- **WHEN** AWS credentials are configured
- **THEN** OIDC federation is used (preferred over static access keys)
- **AND** the IAM role ARN is sourced from GitHub Secrets

### Requirement: Environment variable management via .env.example

A `.env.example` file SHALL be provided at the project root documenting all required and optional environment variables with descriptions and default values.

#### Scenario: Required variables documented

- **GIVEN** the `.env.example` file
- **WHEN** the file is inspected
- **THEN** `ANTHROPIC_API_KEY`, `GOOGLE_FACTCHECK_API_KEY`, and `NEWSAPI_KEY` are listed as required (with placeholder values)

#### Scenario: Optional variables with defaults

- **GIVEN** the `.env.example` file
- **WHEN** the file is inspected
- **THEN** `DATABASE_URL`, `REDIS_URL`, `TEMPORAL_ADDRESS`, `SNAPSHOT_STORE`, `NODE_ENV` are listed with default values for local development
