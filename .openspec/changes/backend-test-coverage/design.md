## Context

The NestJS backend follows Clean Architecture with four layers: Domain, Application (Use Cases), Adapters (Controllers/Presenters), and Infrastructure (TypeORM/Redis/Temporal). The existing test suite has:

- **Domain unit tests** (`src/domain/__tests__/`): Test entity state machines and value objects — these are solid and unchanged.
- **Application unit tests** (`src/application/__tests__/`): Test use cases with jest.fn() mocks for all repositories and ports. They verify call patterns but never touch a real database.
- **Adapter unit tests** (`src/adapters/__tests__/`): Cover `EventController`, `SseEventMapper`, and `VerdictPresenter` — again with mocks.
- **Infrastructure unit tests** (`src/infrastructure/__tests__/`): Cover `RedisStreamAdapter` and `StaticHtmlRenderer`.
- **E2E tests** (`test/app.e2e-spec.ts`): A single 965-line file that bootstraps a NestJS app with in-memory repositories, testing HTTP endpoints, repository CRUD, verdict presentation, and error handling all in one place.

The gap: use cases never run against a real database, and controller tests are conflated with E2E lifecycle tests.

## Goals / Non-Goals

**Goals:**
- Use-case integration tests that exercise TypeORM repositories against an in-process database, validating actual SQL behavior (inserts, lookups, constraint handling)
- Per-controller endpoint tests that isolate HTTP routing, validation, status codes, and presenter formatting from database concerns
- A shared test database module that other test files can import for consistent database setup/teardown
- Clear separation: integration tests validate business logic + persistence; controller tests validate HTTP semantics

**Non-Goals:**
- Rewriting existing domain, adapter, or infrastructure unit tests
- Adding tests for Redis, Temporal, or S3 integrations (those remain mocked)
- End-to-end tests that require running external services (PostgreSQL, Redis, Temporal)
- Performance or load testing

## Decisions

### 1. pg-mem as the embedded database

**Choice**: Use `pg-mem` to provide an in-memory PostgreSQL emulator for integration tests.

**Rationale**: pg-mem implements PostgreSQL's SQL dialect in pure JavaScript, supports TypeORM's synchronize mode, and requires no external processes. This means tests run in CI without a database container. It correctly handles PostgreSQL-specific types (uuid, timestamptz, varchar), which matters for this codebase's ORM entities.

**Alternatives considered**:
- **better-sqlite3**: Would require maintaining separate SQLite-compatible entity definitions or column types. TypeORM's PostgreSQL-specific decorators (`@Column({ type: 'timestamptz' })`) would fail.
- **Testcontainers (PostgreSQL)**: True PostgreSQL fidelity but adds Docker dependency to test runs, 3-5 second startup overhead, and CI complexity.
- **In-memory repositories (current approach)**: Already in use for E2E tests. Doesn't validate SQL behavior, which is the whole point.

### 2. One test file per use case in `tests/use-cases/`

**Choice**: Create `tests/use-cases/<use-case-name>.integration.spec.ts` for each of the 8 use cases.

**Rationale**: Each use case has distinct repository dependencies and side effects. Isolating them per file makes test failures immediately attributable to a specific use case. The `.integration.spec.ts` suffix distinguishes these from the existing `.spec.ts` unit tests in `src/application/__tests__/`.

### 3. One test file per controller in `tests/controllers/`

**Choice**: Create `tests/controllers/<controller-name>.spec.ts` for each of the 6 controllers.

**Rationale**: Controllers inject use cases (not repositories). Mocking at the use case boundary keeps controller tests focused on HTTP concerns: correct status codes, validation pipe behavior, presenter output format, and exception-to-HTTP-error mapping. This matches the Clean Architecture boundary: controllers depend on use cases, not infrastructure.

### 4. Mock use cases (not repos) in controller tests

**Choice**: In controller tests, provide jest.fn() mocks for use case classes. Do not involve repositories or databases.

**Rationale**: The controller's job is to translate HTTP requests into use case calls and format responses. Testing repository behavior in controller tests would make them fragile to database changes and duplicate coverage from integration tests.

### 5. Shared TestDatabaseModule

**Choice**: Create `tests/support/test-database.module.ts` that initializes pg-mem with TypeORM, registers all ORM entities, and exposes a teardown helper.

**Rationale**: Every integration test needs the same database setup. Centralizing this avoids duplication and ensures consistent configuration across all 8 integration test files.

### 6. Separate Jest configuration for integration tests

**Choice**: Add `tests/jest-integration.json` config pointing at `tests/use-cases/` with the `.integration.spec.ts` pattern. Add a `test:integration` npm script.

**Rationale**: Integration tests are slower than unit tests (pg-mem initialization) and should be runnable independently. Keeping them in a separate config lets developers run `npm test` for fast unit tests and `npm run test:integration` for database-backed tests.

### 7. Retain a minimal E2E smoke test

**Choice**: Keep `test/app.e2e-spec.ts` but reduce it to a single lifecycle smoke test (create session → submit claim → get verdict). Move the per-endpoint and per-repository tests into the new directories.

**Rationale**: A single lifecycle test validates that the NestJS module wiring works end-to-end. The current file's per-endpoint and CRUD tests are better served by the new focused test files.

## Risks / Trade-offs

- **pg-mem fidelity gap** → pg-mem doesn't implement every PostgreSQL feature (e.g., some window functions, advanced JSON operators). Mitigation: Our ORM entities use basic column types and simple queries; verify pg-mem compatibility for each entity during implementation.
- **Test speed regression** → pg-mem initialization adds ~200-500ms per test suite. Mitigation: Use `beforeAll` (not `beforeEach`) for database module setup; only reset data between tests, not the schema.
- **Maintenance of two test layers** → Use case logic is now tested in both unit tests (mocked) and integration tests (pg-mem). Mitigation: Unit tests verify edge-case logic and mock interactions; integration tests verify data persistence. Different concerns, complementary coverage.
- **TypeORM synchronize in tests** → Using `synchronize: true` with pg-mem auto-creates tables. If ORM entities drift from production migrations, tests won't catch it. Mitigation: This is acceptable for integration tests; migration correctness is a separate concern.
