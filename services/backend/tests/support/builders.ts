/**
 * ORM entity builder functions for database-backed integration tests.
 *
 * Each builder creates a TypeORM entity instance with sensible defaults
 * and accepts partial overrides. Use these to seed pg-mem before assertions.
 *
 * Domain entity builders (for in-memory/mock tests) live in ./mocks.ts.
 */

import { SessionOrmEntity } from '@infra/typeorm/entities/session.orm-entity';
import { RunOrmEntity } from '@infra/typeorm/entities/run.orm-entity';
import { VerdictOrmEntity } from '@infra/typeorm/entities/verdict.orm-entity';
import { CitationOrmEntity } from '@infra/typeorm/entities/citation.orm-entity';
import { SessionStatus } from '@domain/enums/session-status.enum';
import { RunStatus } from '@domain/enums/run-status.enum';
import { RatingLabel } from '@domain/enums/rating-label.enum';
import { ValidationStatus } from '@domain/enums/validation-status.enum';

// ---------------------------------------------------------------------------
// ORM entity builders — for pg-mem integration tests
// ---------------------------------------------------------------------------

export function buildSessionOrm(
  overrides: Partial<Omit<SessionOrmEntity, 'runs'>> = {},
): SessionOrmEntity {
  const entity = new SessionOrmEntity();
  return Object.assign(entity, {
    sessionId: 'test-session-id',
    status: SessionStatus.Active,
    claim: null,
    createdAt: new Date('2026-01-01T00:00:00Z'),
    frozenAt: null,
    expiresAt: null,
    snapshotUrl: null,
    ...overrides,
  });
}

export function buildRunOrm(
  overrides: Partial<Omit<RunOrmEntity, 'session' | 'verdict'>> = {},
): RunOrmEntity {
  const entity = new RunOrmEntity();
  return Object.assign(entity, {
    runId: 'test-run-id',
    sessionId: 'test-session-id',
    status: RunStatus.Pending,
    phase: null,
    createdAt: new Date('2026-01-01T00:00:00Z'),
    completedAt: null,
    ...overrides,
  });
}

export function buildVerdictOrm(
  overrides: Partial<Omit<VerdictOrmEntity, 'run' | 'citations'>> = {},
): VerdictOrmEntity {
  const entity = new VerdictOrmEntity();
  return Object.assign(entity, {
    verdictId: 'test-verdict-id',
    runId: 'test-run-id',
    factualityScore: 0.75,
    ratingLabel: RatingLabel.MostlyTrue,
    narrative: 'Test narrative',
    signalCount: 5,
    finalizedAt: new Date('2026-01-01T00:00:00Z'),
    ...overrides,
  });
}

export function buildCitationOrm(
  overrides: Partial<Omit<CitationOrmEntity, 'verdict'>> = {},
): CitationOrmEntity {
  const entity = new CitationOrmEntity();
  return Object.assign(entity, {
    citationId: 'test-citation-id',
    verdictId: 'test-verdict-id',
    sourceUrl: 'https://example.com/source',
    sourceName: 'Example Source',
    agent: 'coverage-center',
    observationCode: 'SRC-001',
    validationStatus: ValidationStatus.Live,
    convergenceCount: 2,
    ...overrides,
  });
}
