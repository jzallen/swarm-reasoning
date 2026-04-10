## ADDED Requirements

### Requirement: Helm chart deploys all services to minikube

A Helm chart under `deploy/k8s/` SHALL define Kubernetes resources for all services in the swarm-reasoning stack. The chart SHALL be deployable to minikube with `helm install swarm-reasoning deploy/k8s/`. The chart is a portfolio demonstration artifact, not a production deployment target.

#### Scenario: Chart deploys successfully to minikube

- **GIVEN** minikube is running with the ingress addon enabled
- **WHEN** `helm install swarm-reasoning deploy/k8s/` is executed
- **THEN** all deployments reach the `Ready` state
- **AND** all services are accessible within the cluster

#### Scenario: Backend deployment defined

- **GIVEN** the Helm chart templates
- **WHEN** `deploy/k8s/templates/backend-deployment.yaml` is inspected
- **THEN** the deployment specifies 1 replica
- **AND** the container uses the backend Docker image
- **AND** resource limits (CPU and memory) are defined
- **AND** a readiness probe checks `GET /health` on port 3000
- **AND** environment variables are sourced from ConfigMap and Secret

#### Scenario: Agent service deployment defined

- **GIVEN** the Helm chart templates
- **WHEN** `deploy/k8s/templates/agent-service-deployment.yaml` is inspected
- **THEN** the deployment specifies 1 replica
- **AND** resource limits are defined
- **AND** no Service resource is needed (worker-only)

#### Scenario: Ingress routes traffic to backend

- **GIVEN** the Helm chart templates
- **WHEN** `deploy/k8s/templates/backend-ingress.yaml` is inspected
- **THEN** paths `/api/*`, `/sessions/*`, and `/health` route to the backend service on port 3000

#### Scenario: Data services use appropriate resource types

- **GIVEN** the Helm chart templates
- **WHEN** PostgreSQL templates are inspected
- **THEN** PostgreSQL uses a StatefulSet with a PersistentVolumeClaim
- **AND** Redis uses a Deployment

#### Scenario: Values.yaml provides configuration

- **GIVEN** `deploy/k8s/values.yaml`
- **WHEN** the file is inspected
- **THEN** image tags are parameterized for all services
- **AND** replica counts are parameterized
- **AND** resource limits are parameterized
- **AND** API keys are referenced from a Kubernetes Secret

### Requirement: Helm chart mirrors Docker Compose topology

The Helm chart SHALL define resources for all 8 services present in the Docker Compose file: frontend, backend, agent-service, temporal, temporal-ui, temporal-db (PostgreSQL for Temporal), postgresql (application database), and redis.

#### Scenario: All 8 services have Kubernetes resources

- **GIVEN** the Helm chart templates directory
- **WHEN** the templates are listed
- **THEN** deployment/statefulset resources exist for: frontend, backend, agent-service, temporal, temporal-ui, temporal-db, postgresql, redis
- **AND** ClusterIP services exist for: frontend, backend, temporal, temporal-ui, temporal-db, postgresql, redis
