## 1. Setup and Infrastructure

- [ ] 1.1 Add `pg-mem` as a devDependency in `services/backend/package.json`
- [ ] 1.2 Create `tests/support/test-database.module.ts` — shared module that initializes pg-mem with TypeORM DataSource, registers all 4 ORM entities, provides TypeORM repositories, mocks non-DB ports (TemporalClient, StreamReader, SnapshotStore, HtmlRenderer), and exports `createTestingModule()` + `clearDatabase()` helpers
- [ ] 1.3 Create `tests/jest-integration.json` — Jest config for integration tests (rootDir: `tests/use-cases`, pattern: `*.integration.spec.ts`, same module aliases as main config)
- [ ] 1.4 Add `test:integration` and `test:controllers` npm scripts to `package.json`

## 2. Use-Case Integration Tests

- [ ] 2.1 Create `tests/use-cases/create-session.integration.spec.ts` — test session creation persists to DB with valid UUID, Active status, and createdAt
- [ ] 2.2 Create `tests/use-cases/submit-claim.integration.spec.ts` — test claim submission creates Run in DB, sets claim on session, calls Temporal mock; test duplicate claim ConflictException; test frozen session UnprocessableEntityException; test Temporal failure transitions Run to Failed in DB
- [ ] 2.3 Create `tests/use-cases/get-session.integration.spec.ts` — test retrieval of existing session; test NotFoundException for missing session
- [ ] 2.4 Create `tests/use-cases/get-verdict.integration.spec.ts` — test verdict retrieval with citations from DB; test NotFoundException when no verdict exists
- [ ] 2.5 Create `tests/use-cases/finalize-session.integration.spec.ts` — test session transitions to Frozen with snapshotUrl; test verdict and citations persisted; test mock SnapshotStore called
- [ ] 2.6 Create `tests/use-cases/cleanup-expired-sessions.integration.spec.ts` — test expired sessions and associated data deleted from DB; test active sessions untouched
- [ ] 2.7 Create `tests/use-cases/stream-progress.integration.spec.ts` — test async generator yields events for valid session; test GoneException for expired session
- [ ] 2.8 Create `tests/use-cases/get-observations.integration.spec.ts` — test observation retrieval delegates to mock StreamReader with DB-validated session/run

## 3. Controller Endpoint Tests

- [ ] 3.1 Create `tests/controllers/session.controller.spec.ts` — test POST /sessions returns 201; test GET /sessions/:id returns 200; test 404 from use case; test invalid UUID returns 400
- [ ] 3.2 Create `tests/controllers/claim.controller.spec.ts` — test POST returns 202; test validation (empty, missing, extra fields → 400); test NotFoundException → 404, ConflictException → 409, UnprocessableEntityException → 422
- [ ] 3.3 Create `tests/controllers/verdict.controller.spec.ts` — test GET returns 200 with formatted verdict; test NotFoundException → 404
- [ ] 3.4 Create `tests/controllers/event.controller.spec.ts` — test SSE headers set; test NotFoundException → 404
- [ ] 3.5 Create `tests/controllers/health.controller.spec.ts` — test 200 when all healthy; test 503 when DataSource fails
- [ ] 3.6 Create `tests/controllers/observation.controller.spec.ts` — test GET returns 200 with observations; test NotFoundException → 404

## 4. E2E Cleanup and Verification

- [ ] 4.1 Reduce `test/app.e2e-spec.ts` to a single lifecycle smoke test (create → claim → verdict) and remove tests now covered by integration and controller test files
- [ ] 4.2 Run all test suites (`npm test`, `npm run test:integration`, `npm run test:controllers`, `npm run test:e2e`) and verify passing
