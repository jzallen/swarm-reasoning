/* eslint-disable @typescript-eslint/require-await */
/**
 * Mock factories for external services used in integration and e2e tests.
 *
 * Provides in-memory repository implementations, mock service adapters,
 * and entity factory helpers for the backend test suite.
 */

import { Session } from '@domain/entities/session.entity';
import { Run } from '@domain/entities/run.entity';
import { Verdict } from '@domain/entities/verdict.entity';
import { Citation } from '@domain/entities/citation.entity';
import { ProgressEvent } from '@domain/entities/progress-event.entity';
import { SessionStatus } from '@domain/enums/session-status.enum';
import { RunStatus } from '@domain/enums/run-status.enum';
import { RatingLabel } from '@domain/enums/rating-label.enum';
import { ValidationStatus } from '@domain/enums/validation-status.enum';
import { ProgressPhase } from '@domain/enums/progress-phase.enum';
import { ProgressType } from '@domain/enums/progress-type.enum';
import type { SessionRepository } from '@app/interfaces/session.repository';
import type { RunRepository } from '@app/interfaces/run.repository';
import type { VerdictRepository } from '@app/interfaces/verdict.repository';
import type { CitationRepository } from '@app/interfaces/citation.repository';
import type { TemporalClientPort } from '@app/interfaces/temporal-client.interface';
import type { StreamReader } from '@app/interfaces/stream-reader.interface';
import type { SnapshotStore } from '@app/interfaces/snapshot-store.interface';
import type { HtmlRenderer } from '@app/interfaces/html-renderer.interface';
import {
  SESSION_REPOSITORY,
  RUN_REPOSITORY,
  VERDICT_REPOSITORY,
  CITATION_REPOSITORY,
  TEMPORAL_CLIENT,
  STREAM_READER,
  SNAPSHOT_STORE,
  HTML_RENDERER,
} from '@app/interfaces';

// ---------------------------------------------------------------------------
// Entity factories — sensible defaults with optional overrides
// ---------------------------------------------------------------------------

export function buildSession(
  overrides: Partial<ConstructorParameters<typeof Session>[0]> = {},
): Session {
  return new Session({
    sessionId: 'test-session-id',
    status: SessionStatus.Active,
    createdAt: new Date('2026-01-01T00:00:00Z'),
    ...overrides,
  });
}

export function buildRun(
  overrides: Partial<ConstructorParameters<typeof Run>[0]> = {},
): Run {
  return new Run({
    runId: 'test-run-id',
    sessionId: 'test-session-id',
    status: RunStatus.Pending,
    createdAt: new Date('2026-01-01T00:00:00Z'),
    ...overrides,
  });
}

export function buildVerdict(
  overrides: Partial<ConstructorParameters<typeof Verdict>[0]> = {},
): Verdict {
  return new Verdict({
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

export function buildCitation(
  overrides: Partial<ConstructorParameters<typeof Citation>[0]> = {},
): Citation {
  return new Citation({
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

export function buildProgressEvent(
  overrides: Partial<ConstructorParameters<typeof ProgressEvent>[0]> = {},
): ProgressEvent {
  return new ProgressEvent({
    runId: 'test-run-id',
    agent: 'ingestion-agent',
    phase: ProgressPhase.Ingestion,
    type: ProgressType.AgentStarted,
    message: 'Agent started',
    timestamp: new Date('2026-01-01T00:00:00Z'),
    entryId: '1-0',
    ...overrides,
  });
}

// ---------------------------------------------------------------------------
// In-memory repository implementations
// ---------------------------------------------------------------------------

export class InMemorySessionRepository implements SessionRepository {
  private store = new Map<string, Session>();

  async save(session: Session): Promise<Session> {
    this.store.set(session.sessionId, session);
    return session;
  }

  async findById(sessionId: string): Promise<Session | null> {
    return this.store.get(sessionId) ?? null;
  }

  async findExpiredSessions(): Promise<Session[]> {
    return [...this.store.values()].filter((s) => s.isExpired());
  }

  async delete(sessionId: string): Promise<void> {
    this.store.delete(sessionId);
  }

  clear(): void {
    this.store.clear();
  }
}

export class InMemoryRunRepository implements RunRepository {
  private store = new Map<string, Run>();

  async save(run: Run): Promise<Run> {
    this.store.set(run.runId, run);
    return run;
  }

  async findById(runId: string): Promise<Run | null> {
    return this.store.get(runId) ?? null;
  }

  async findBySessionId(sessionId: string): Promise<Run | null> {
    for (const run of this.store.values()) {
      if (run.sessionId === sessionId) return run;
    }
    return null;
  }

  clear(): void {
    this.store.clear();
  }
}

export class InMemoryVerdictRepository implements VerdictRepository {
  private store = new Map<string, Verdict>();

  async save(verdict: Verdict): Promise<Verdict> {
    this.store.set(verdict.verdictId, verdict);
    return verdict;
  }

  async findByRunId(runId: string): Promise<Verdict | null> {
    for (const v of this.store.values()) {
      if (v.runId === runId) return v;
    }
    return null;
  }

  clear(): void {
    this.store.clear();
  }
}

export class InMemoryCitationRepository implements CitationRepository {
  private store: Citation[] = [];

  async saveMany(citations: Citation[]): Promise<Citation[]> {
    this.store.push(...citations);
    return citations;
  }

  async findByVerdictId(verdictId: string): Promise<Citation[]> {
    return this.store.filter((c) => c.verdictId === verdictId);
  }

  clear(): void {
    this.store = [];
  }
}

// ---------------------------------------------------------------------------
// Mock external service adapters
// ---------------------------------------------------------------------------

export class MockTemporalClient implements TemporalClientPort {
  calls: { runId: string; sessionId: string; claimText: string }[] = [];

  async startClaimVerificationWorkflow(
    runId: string,
    sessionId: string,
    claimText: string,
  ): Promise<void> {
    this.calls.push({ runId, sessionId, claimText });
  }

  async getWorkflowStatus(): Promise<string> {
    return 'RUNNING';
  }

  async cancelWorkflow(): Promise<void> {}

  clear(): void {
    this.calls = [];
  }
}

export class MockStreamReader implements StreamReader {
  private observations: Record<string, unknown>[] = [];
  private progressEvents: ProgressEvent[] = [];

  setObservations(obs: Record<string, unknown>[]): void {
    this.observations = obs;
  }

  setProgressEvents(events: ProgressEvent[]): void {
    this.progressEvents = events;
  }

  async *readProgress(): AsyncGenerator<ProgressEvent, void, unknown> {
    for (const event of this.progressEvents) {
      yield event;
    }
  }

  async readObservations(): Promise<Record<string, unknown>[]> {
    return this.observations;
  }

  async readAllProgressEvents(): Promise<ProgressEvent[]> {
    return this.progressEvents;
  }

  async deleteStreams(): Promise<void> {}

  async ping(): Promise<void> {}

  clear(): void {
    this.observations = [];
    this.progressEvents = [];
  }
}

export class MockSnapshotStore implements SnapshotStore {
  uploads: { sessionId: string; html: string }[] = [];

  async upload(sessionId: string, html: string): Promise<string> {
    this.uploads.push({ sessionId, html });
    return `https://snapshots.example.com/${sessionId}.html`;
  }

  async delete(): Promise<void> {}

  clear(): void {
    this.uploads = [];
  }
}

export class MockHtmlRenderer implements HtmlRenderer {
  render(): string {
    return '<html><body>mock snapshot</body></html>';
  }
}

export class MockDataSource {
  queryResult: unknown = [{ '?column?': 1 }];
  shouldFail = false;

  async query(): Promise<unknown> {
    if (this.shouldFail) throw new Error('db unreachable');
    return this.queryResult;
  }
}

// ---------------------------------------------------------------------------
// Jest mock factories — creates plain objects with jest.fn() stubs
// ---------------------------------------------------------------------------

export function mockSessionRepository() {
  return {
    save: jest.fn((s: Session) => Promise.resolve(s)),
    findById: jest
      .fn<Promise<Session | null>, [string]>()
      .mockResolvedValue(null),
    findExpiredSessions: jest
      .fn<Promise<Session[]>, []>()
      .mockResolvedValue([]),
    delete: jest.fn<Promise<void>, [string]>().mockResolvedValue(undefined),
  };
}

export function mockRunRepository() {
  return {
    save: jest.fn((r: Run) => Promise.resolve(r)),
    findById: jest.fn<Promise<Run | null>, [string]>().mockResolvedValue(null),
    findBySessionId: jest
      .fn<Promise<Run | null>, [string]>()
      .mockResolvedValue(null),
  };
}

export function mockVerdictRepository() {
  return {
    save: jest.fn((v: Verdict) => Promise.resolve(v)),
    findByRunId: jest
      .fn<Promise<Verdict | null>, [string]>()
      .mockResolvedValue(null),
  };
}

export function mockCitationRepository() {
  return {
    saveMany: jest.fn((c: Citation[]) => Promise.resolve(c)),
    findByVerdictId: jest
      .fn<Promise<Citation[]>, [string]>()
      .mockResolvedValue([]),
  };
}

export function mockTemporalClient() {
  return {
    startClaimVerificationWorkflow: jest
      .fn<Promise<void>, [string, string, string, string?, string?]>()
      .mockResolvedValue(undefined),
    getWorkflowStatus: jest
      .fn<Promise<string>, [string]>()
      .mockResolvedValue('RUNNING'),
    cancelWorkflow: jest
      .fn<Promise<void>, [string, string?]>()
      .mockResolvedValue(undefined),
  };
}

export function mockStreamReader() {
  return {
    readProgress: jest.fn(async function* () {}),
    readObservations: jest
      .fn<Promise<Record<string, unknown>[]>, [string]>()
      .mockResolvedValue([]),
    readAllProgressEvents: jest
      .fn<Promise<ProgressEvent[]>, [string]>()
      .mockResolvedValue([]),
    deleteStreams: jest
      .fn<Promise<void>, [string]>()
      .mockResolvedValue(undefined),
    ping: jest.fn<Promise<void>, []>().mockResolvedValue(undefined),
  };
}

export function mockSnapshotStore() {
  return {
    upload: jest
      .fn<Promise<string>, [string, string]>()
      .mockResolvedValue('https://snapshots.example.com/test.html'),
    delete: jest.fn<Promise<void>, [string]>().mockResolvedValue(undefined),
  };
}

export function mockHtmlRenderer() {
  return {
    render: jest
      .fn<string, [Verdict, Citation[], Session, ProgressEvent[]]>()
      .mockReturnValue('<html><body>mock snapshot</body></html>'),
  };
}

// ---------------------------------------------------------------------------
// NestJS test module provider builder
// ---------------------------------------------------------------------------

export interface MockProviderSet {
  sessionRepo: InMemorySessionRepository;
  runRepo: InMemoryRunRepository;
  verdictRepo: InMemoryVerdictRepository;
  citationRepo: InMemoryCitationRepository;
  temporalClient: MockTemporalClient;
  streamReader: MockStreamReader;
  snapshotStore: MockSnapshotStore;
  htmlRenderer: MockHtmlRenderer;
  dataSource: MockDataSource;
  providers: {
    provide: symbol | (abstract new (...args: unknown[]) => unknown);
    useValue: unknown;
  }[];
}

export function buildMockProviders(): MockProviderSet {
  const sessionRepo = new InMemorySessionRepository();
  const runRepo = new InMemoryRunRepository();
  const verdictRepo = new InMemoryVerdictRepository();
  const citationRepo = new InMemoryCitationRepository();
  const temporalClient = new MockTemporalClient();
  const streamReader = new MockStreamReader();
  const snapshotStore = new MockSnapshotStore();
  const htmlRenderer = new MockHtmlRenderer();
  const dataSource = new MockDataSource();

  return {
    sessionRepo,
    runRepo,
    verdictRepo,
    citationRepo,
    temporalClient,
    streamReader,
    snapshotStore,
    htmlRenderer,
    dataSource,
    providers: [
      { provide: SESSION_REPOSITORY, useValue: sessionRepo },
      { provide: RUN_REPOSITORY, useValue: runRepo },
      { provide: VERDICT_REPOSITORY, useValue: verdictRepo },
      { provide: CITATION_REPOSITORY, useValue: citationRepo },
      { provide: TEMPORAL_CLIENT, useValue: temporalClient },
      { provide: STREAM_READER, useValue: streamReader },
      { provide: SNAPSHOT_STORE, useValue: snapshotStore },
      { provide: HTML_RENDERER, useValue: htmlRenderer },
    ],
  };
}

export function clearAllMocks(mocks: MockProviderSet): void {
  mocks.sessionRepo.clear();
  mocks.runRepo.clear();
  mocks.verdictRepo.clear();
  mocks.citationRepo.clear();
  mocks.temporalClient.clear();
  mocks.streamReader.clear();
  mocks.snapshotStore.clear();
}
