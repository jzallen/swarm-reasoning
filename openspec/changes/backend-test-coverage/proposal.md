## Why

The backend test suite relies on jest.fn() mocks for all repository and port dependencies, which means use-case tests never verify actual database behavior (writes, reads, constraint violations). The single monolithic E2E file (`test/app.e2e-spec.ts`) mixes controller routing concerns with repository CRUD verification, making it hard to isolate regressions. There are no per-controller test files except `event.controller.spec.ts`, so most controller error-handling paths are only tested through the E2E monolith.

## What Changes

- **Add use-case integration tests** (`tests/use-cases/`): One test file per use case, backed by an embedded in-process database (pg-mem or better-sqlite3 via TypeORM) so tests exercise real SQL without external dependencies. Each test validates: the use case's return value, side effects persisted in the database, and error paths.
- **Add per-controller endpoint tests** (`tests/controllers/`): One test file per controller. Mock use cases (not repositories) to test that controllers handle HTTP semantics correctly: status codes, response shaping via presenters, validation pipe behavior, and error/exception mapping.
- **Break apart the E2E monolith**: Migrate coverage from `test/app.e2e-spec.ts` into the two new test directories above. The E2E file can be removed or reduced to a single smoke-test lifecycle flow.
- **Add shared test infrastructure**: Create a reusable test database module that provisions and tears down the embedded database per test suite.

## Capabilities

### New Capabilities
- `usecase-integration-tests`: Use-case-level integration tests backed by an embedded database, one file per use case
- `controller-endpoint-tests`: Per-controller HTTP tests with mocked use cases, one file per controller
- `test-database-module`: Shared NestJS testing module that provides an embedded database for integration tests

### Modified Capabilities

## Impact

- **Code**: `services/backend/` — new `tests/use-cases/`, `tests/controllers/`, and `tests/support/` directories; possible removal of `test/app.e2e-spec.ts`
- **Dependencies**: New dev dependency on `pg-mem` (in-memory PostgreSQL emulator compatible with TypeORM)
- **CI**: Test commands may need updating to include new test directories; coverage thresholds should increase
- **Existing tests**: Domain unit tests (`src/domain/__tests__/`), adapter unit tests (`src/adapters/__tests__/`), and infrastructure unit tests remain unchanged
