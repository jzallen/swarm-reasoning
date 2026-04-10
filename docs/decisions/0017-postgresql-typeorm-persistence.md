---
status: accepted
date: 2026-04-10
deciders: []
---

# ADR-0017: PostgreSQL with TypeORM for Persistence

## Context and Problem Statement

The system needs durable storage for claims, sessions, verdicts, citations, and progress events. TypeORM is specified for data access. The storage must be cost-effective for a portfolio project with low traffic -- ideally scaling to near-zero cost when idle.

## Decision Drivers

- TypeORM is required for data access in the NestJS backend
- Production hosting cost must be minimal for a portfolio project with sporadic traffic
- Local development must use the same engine as production to avoid dialect mismatches
- Docker image size and ARM support matter for local development on Apple Silicon

## Considered Options

1. **MSSQL** -- Specified in the job description's legacy context. Full-featured but expensive on RDS (license costs baked into instance pricing), heavy Docker image (~1.5 GB), poor ARM/Apple Silicon support in Docker, no scale-to-zero managed offering.
2. **PostgreSQL** -- Free and open source. Lightweight Docker image (~200 MB), excellent ARM support, Aurora Serverless v2 provides scale-to-zero in production. Broad ecosystem and tooling.
3. **SQLite** -- Simplest local option with zero configuration. However, no managed cloud offering for production, limited concurrency under write-heavy workloads, and no streaming replication.

## Decision Outcome

Chosen option: "PostgreSQL", because TypeORM abstracts the engine (skills demonstrated transfer directly to MSSQL), Aurora Serverless v2 scales to zero for minimal cost, and PostgreSQL is the most cost-effective option for a portfolio deployment.

**Local development**: PostgreSQL runs in Docker alongside the other services in the Compose stack. The image is lightweight and supports ARM natively.

**Production**: Aurora Serverless v2 with minimum capacity of 0.5 ACU. When idle, cost drops to near zero. The cluster scales automatically under load without provisioning changes.

**TypeORM integration**: TypeORM entities are defined in the infrastructure layer of the Clean Architecture (ADR-0015). Repository interfaces are defined in the interface adapters layer; TypeORM implementations (`TypeOrmSessionRepository`, `TypeOrmVerdictRepository`, `TypeOrmCitationRepository`) live in infrastructure. Entity definitions are engine-agnostic -- switching to MSSQL requires only a connection configuration change.

**Migrations**: TypeORM migrations are generated from entity definitions and run on application startup in development. In production, migrations run as a pre-deployment step.

### Consequences

- Good, because Aurora Serverless v2 has near-zero cost when idle, suitable for a portfolio project
- Good, because TypeORM entity definitions are engine-agnostic and transfer directly to MSSQL
- Good, because PostgreSQL has a broad tooling ecosystem (pgAdmin, psql, pg_dump) and extensive community support
- Bad, because MSSQL is not directly demonstrated, so MSSQL-specific features (T-SQL stored procedures, SSMS) are not shown
- Neutral, because TypeORM migrations work identically across PostgreSQL and MSSQL -- the migration files are engine-independent

## More Information

- ADR-0015: NestJS Backend with Clean Architecture (repository interfaces and infrastructure layer)
- ADR-0014: Three-Service Architecture (PostgreSQL serves the NestJS backend service)
