## ADDED Requirements

### Requirement: CleanupExpiredSessionsUseCase deletes all resources for expired sessions

The `CleanupExpiredSessionsUseCase` SHALL query PostgreSQL for sessions where `status = 'frozen'` and `expiresAt < NOW()`. For each expired session, it SHALL delete: the snapshot file, the Redis streams, and the database rows. The cleanup SHALL be idempotent and handle partial failures gracefully.

#### Scenario: Cleanup identifies expired sessions

- **GIVEN** 3 frozen sessions exist: session A (expiresAt = yesterday), session B (expiresAt = tomorrow), session C (expiresAt = 2 days ago)
- **WHEN** the cleanup use case runs
- **THEN** sessions A and C are identified for cleanup
- **AND** session B is not affected

#### Scenario: Cleanup deletes snapshot

- **GIVEN** expired session A has a snapshot at `snapshotUrl`
- **WHEN** the cleanup processes session A
- **THEN** `SnapshotStore.delete(sessionA.id)` is called

#### Scenario: Cleanup deletes Redis streams

- **GIVEN** expired session A has runId `claim-123-run-001`
- **WHEN** the cleanup processes session A
- **THEN** Redis key `progress:claim-123-run-001` is deleted
- **AND** all Redis keys matching `reasoning:claim-123-run-001:*` are deleted

#### Scenario: Cleanup deletes database rows

- **GIVEN** expired session A has associated verdict and citation rows
- **WHEN** the cleanup processes session A
- **THEN** the session row is deleted from PostgreSQL
- **AND** the associated verdict and citation rows are cascade-deleted

#### Scenario: No expired sessions

- **GIVEN** all frozen sessions have `expiresAt` in the future
- **WHEN** the cleanup use case runs
- **THEN** no deletions occur
- **AND** the use case completes successfully

#### Scenario: Partial failure continues to next session

- **GIVEN** expired sessions A, B, and C are identified for cleanup
- **AND** snapshot deletion for session B fails with an I/O error
- **WHEN** the cleanup processes all three sessions
- **THEN** session A is fully cleaned up
- **AND** session B's failure is logged as an error
- **AND** session C is fully cleaned up
- **AND** the use case does not throw (it returns a summary of successes and failures)

#### Scenario: Idempotent cleanup

- **GIVEN** expired session A was partially cleaned up in a prior run (snapshot deleted, but DB row remains)
- **WHEN** the cleanup runs again
- **THEN** `SnapshotStore.delete(sessionA.id)` is called and does not throw (no-op for missing snapshot)
- **AND** Redis stream deletion is attempted and does not throw (no-op for missing keys)
- **AND** the database row is deleted

### Requirement: Cleanup runs on a schedule

The cleanup SHALL run on a recurring schedule (every 6 hours). It SHALL be implemented as either a Temporal scheduled workflow or a NestJS cron job using `@nestjs/schedule`.

#### Scenario: Scheduled execution via Temporal

- **GIVEN** a Temporal schedule `cleanup-expired-sessions` configured to run every 6 hours
- **WHEN** the schedule fires
- **THEN** the `CleanupExpiredSessionsUseCase` is executed as a Temporal activity

#### Scenario: Scheduled execution via NestJS cron (alternative)

- **GIVEN** a NestJS cron job decorated with `@Cron('0 */6 * * *')`
- **WHEN** the cron fires
- **THEN** the `CleanupExpiredSessionsUseCase` is executed

### Requirement: FinalizeSessionUseCase sets expiration on freeze

When a session is frozen, the `FinalizeSessionUseCase` SHALL set `expiresAt` to `NOW() + 3 days`. This is the timestamp used by the cleanup use case to identify expired sessions.

#### Scenario: Expiration set on freeze

- **GIVEN** an active session being finalized at `2026-04-10T12:00:00Z`
- **WHEN** the session is frozen
- **THEN** `session.expiresAt` is set to `2026-04-13T12:00:00Z`
- **AND** `session.frozenAt` is set to `2026-04-10T12:00:00Z`
- **AND** `session.status` is set to `frozen`
