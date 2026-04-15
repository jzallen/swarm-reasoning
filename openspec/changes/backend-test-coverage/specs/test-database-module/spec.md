## ADDED Requirements

### Requirement: Shared test database module provides pg-mem-backed TypeORM DataSource
The system SHALL provide a `TestDatabaseModule` at `tests/support/test-database.module.ts` that creates a pg-mem-backed TypeORM `DataSource` with all ORM entities registered (`SessionOrmEntity`, `RunOrmEntity`, `VerdictOrmEntity`, `CitationOrmEntity`). The module SHALL use `synchronize: true` to auto-create tables. It SHALL export a `createTestingModule()` function that returns a configured NestJS `TestingModule` with all repository providers bound to their TypeORM implementations.

#### Scenario: Module initializes with all entities
- **WHEN** a test calls `createTestingModule()`
- **THEN** the returned module SHALL have a working `DataSource` connected to pg-mem
- **AND** all four entity tables (sessions, runs, verdicts, citations) SHALL exist

#### Scenario: Module provides real TypeORM repositories
- **WHEN** a test resolves `SESSION_REPOSITORY` from the module
- **THEN** it SHALL receive a `TypeOrmSessionRepository` backed by pg-mem (not a mock)

### Requirement: Test database supports per-test data isolation
The module SHALL export a `clearDatabase()` helper that truncates all tables between tests without dropping/recreating the schema.

#### Scenario: Data cleared between tests
- **WHEN** test A saves a session, then `clearDatabase()` runs, then test B queries sessions
- **THEN** test B SHALL find zero sessions

### Requirement: Test database module provides mock ports for non-DB dependencies
The module SHALL provide jest.fn() mock implementations for `TEMPORAL_CLIENT`, `STREAM_READER`, `SNAPSHOT_STORE`, and `HTML_RENDERER` so that integration tests only need a real database — all external service ports remain mocked.

#### Scenario: Non-DB ports are mocked
- **WHEN** a test resolves `TEMPORAL_CLIENT` from the module
- **THEN** it SHALL receive a mock object with jest.fn() methods
