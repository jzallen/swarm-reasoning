import { Test, TestingModule } from '@nestjs/testing';
import { INestApplication, ValidationPipe } from '@nestjs/common';
import request from 'supertest';
import { App } from 'supertest/types';
import { ConfigModule } from '@nestjs/config';
import { DataSource } from 'typeorm';
import { Session } from '@domain/entities/session.entity';
import { Run } from '@domain/entities/run.entity';
import { Verdict } from '@domain/entities/verdict.entity';
import { Citation } from '@domain/entities/citation.entity';
import {
  SessionStatus,
  RunStatus,
  RatingLabel,
  ValidationStatus,
} from '@domain/enums';
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
import {
  CreateSessionUseCase,
  GetSessionUseCase,
  SubmitClaimUseCase,
  GetVerdictUseCase,
} from '@app/use-cases';
import { SessionController } from '@adapters/controllers/session.controller';
import { ClaimController } from '@adapters/controllers/claim.controller';
import { VerdictController } from '@adapters/controllers/verdict.controller';
import { HealthController } from '@adapters/controllers/health.controller';
import { VerdictPresenter } from '@adapters/presenters/verdict.presenter';
import { SessionPresenter } from '@adapters/presenters/session.presenter';
import { GlobalExceptionFilter } from '@adapters/filters/http-exception.filter';

// ---------------------------------------------------------------------------
// In-memory repository implementations
// ---------------------------------------------------------------------------

class InMemorySessionRepository {
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

  clear() {
    this.store.clear();
  }
}

class InMemoryRunRepository {
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

  clear() {
    this.store.clear();
  }
}

class InMemoryVerdictRepository {
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

  clear() {
    this.store.clear();
  }
}

class InMemoryCitationRepository {
  private store: Citation[] = [];

  async saveMany(citations: Citation[]): Promise<Citation[]> {
    this.store.push(...citations);
    return citations;
  }

  async findByVerdictId(verdictId: string): Promise<Citation[]> {
    return this.store.filter((c) => c.verdictId === verdictId);
  }

  clear() {
    this.store = [];
  }
}

// ---------------------------------------------------------------------------
// Mock Temporal client
// ---------------------------------------------------------------------------

class MockTemporalClient {
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

  clear() {
    this.calls = [];
  }
}

// ---------------------------------------------------------------------------
// Mock StreamReader
// ---------------------------------------------------------------------------

class MockStreamReader {
  private observations: Record<string, unknown>[] = [];

  setObservations(obs: Record<string, unknown>[]) {
    this.observations = obs;
  }

  async *readProgress() {
    // noop
  }

  async readObservations(): Promise<Record<string, unknown>[]> {
    return this.observations;
  }

  async readAllProgressEvents() {
    return [];
  }

  async deleteStreams(): Promise<void> {}

  async ping(): Promise<void> {}
}

// ---------------------------------------------------------------------------
// Mock DataSource (for HealthController)
// ---------------------------------------------------------------------------

class MockDataSource {
  queryResult: unknown = [{ '?column?': 1 }];
  shouldFail = false;

  async query() {
    if (this.shouldFail) throw new Error('db unreachable');
    return this.queryResult;
  }
}

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

function buildTestModule() {
  const sessionRepo = new InMemorySessionRepository();
  const runRepo = new InMemoryRunRepository();
  const verdictRepo = new InMemoryVerdictRepository();
  const citationRepo = new InMemoryCitationRepository();
  const temporalClient = new MockTemporalClient();
  const streamReader = new MockStreamReader();
  const mockDataSource = new MockDataSource();

  return {
    sessionRepo,
    runRepo,
    verdictRepo,
    citationRepo,
    temporalClient,
    streamReader,
    mockDataSource,
    providers: [
      { provide: SESSION_REPOSITORY, useValue: sessionRepo },
      { provide: RUN_REPOSITORY, useValue: runRepo },
      { provide: VERDICT_REPOSITORY, useValue: verdictRepo },
      { provide: CITATION_REPOSITORY, useValue: citationRepo },
      { provide: TEMPORAL_CLIENT, useValue: temporalClient },
      { provide: STREAM_READER, useValue: streamReader },
      { provide: SNAPSHOT_STORE, useValue: { upload: jest.fn(), delete: jest.fn() } },
      { provide: HTML_RENDERER, useValue: { render: jest.fn(() => '<html></html>') } },
    ],
  };
}

// ---------------------------------------------------------------------------
// E2E Tests
// ---------------------------------------------------------------------------

describe('Backend API (e2e)', () => {
  let app: INestApplication<App>;
  let sessionRepo: InMemorySessionRepository;
  let runRepo: InMemoryRunRepository;
  let verdictRepo: InMemoryVerdictRepository;
  let citationRepo: InMemoryCitationRepository;
  let temporalClient: MockTemporalClient;
  let streamReader: MockStreamReader;
  let mockDataSource: MockDataSource;

  beforeAll(async () => {
    const ctx = buildTestModule();
    sessionRepo = ctx.sessionRepo;
    runRepo = ctx.runRepo;
    verdictRepo = ctx.verdictRepo;
    citationRepo = ctx.citationRepo;
    temporalClient = ctx.temporalClient;
    streamReader = ctx.streamReader;
    mockDataSource = ctx.mockDataSource;

    const moduleFixture: TestingModule = await Test.createTestingModule({
      imports: [ConfigModule.forRoot({ isGlobal: true })],
      controllers: [
        SessionController,
        ClaimController,
        VerdictController,
        HealthController,
      ],
      providers: [
        ...ctx.providers,
        { provide: DataSource, useValue: mockDataSource },
        CreateSessionUseCase,
        GetSessionUseCase,
        SubmitClaimUseCase,
        GetVerdictUseCase,
        VerdictPresenter,
        SessionPresenter,
      ],
    }).compile();

    app = moduleFixture.createNestApplication();
    app.useGlobalPipes(
      new ValidationPipe({
        whitelist: true,
        forbidNonWhitelisted: true,
        transform: true,
      }),
    );
    app.useGlobalFilters(new GlobalExceptionFilter());
    await app.init();
  });

  afterAll(async () => {
    await app.close();
  });

  beforeEach(() => {
    sessionRepo.clear();
    runRepo.clear();
    verdictRepo.clear();
    citationRepo.clear();
    temporalClient.clear();
  });

  // -----------------------------------------------------------------------
  // POST /sessions — 201
  // -----------------------------------------------------------------------

  describe('POST /sessions', () => {
    it('should create a new session and return 201', async () => {
      const res = await request(app.getHttpServer())
        .post('/sessions')
        .expect(201);

      expect(res.body).toHaveProperty('sessionId');
      expect(res.body.status).toBe('active');
      expect(res.body.createdAt).toBeDefined();
      expect(res.body.frozenAt).toBeNull();
      expect(res.body.expiresAt).toBeNull();
      expect(res.body.snapshotUrl).toBeNull();
    });

    it('should persist the session in the repository', async () => {
      const res = await request(app.getHttpServer())
        .post('/sessions')
        .expect(201);

      const saved = await sessionRepo.findById(res.body.sessionId);
      expect(saved).not.toBeNull();
      expect(saved!.status).toBe(SessionStatus.Active);
    });

    it('should generate a valid UUID for sessionId', async () => {
      const res = await request(app.getHttpServer())
        .post('/sessions')
        .expect(201);

      const uuidRegex =
        /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
      expect(res.body.sessionId).toMatch(uuidRegex);
    });
  });

  // -----------------------------------------------------------------------
  // POST /sessions/:sessionId/claims — 202 + workflow start
  // -----------------------------------------------------------------------

  describe('POST /sessions/:sessionId/claims', () => {
    let sessionId: string;

    beforeEach(async () => {
      const res = await request(app.getHttpServer())
        .post('/sessions')
        .expect(201);
      sessionId = res.body.sessionId;
    });

    it('should accept a claim and return 202', async () => {
      const res = await request(app.getHttpServer())
        .post(`/sessions/${sessionId}/claims`)
        .send({ claimText: 'The sky is blue' })
        .expect(202);

      expect(res.body.sessionId).toBe(sessionId);
      expect(res.body.claim).toBe('The sky is blue');
      expect(res.body.status).toBe('active');
    });

    it('should start a Temporal workflow', async () => {
      await request(app.getHttpServer())
        .post(`/sessions/${sessionId}/claims`)
        .send({ claimText: 'Earth is round' })
        .expect(202);

      expect(temporalClient.calls).toHaveLength(1);
      expect(temporalClient.calls[0].sessionId).toBe(sessionId);
      expect(temporalClient.calls[0].claimText).toBe('Earth is round');
      expect(temporalClient.calls[0].runId).toBeDefined();
    });

    it('should reject empty claimText with 400', async () => {
      await request(app.getHttpServer())
        .post(`/sessions/${sessionId}/claims`)
        .send({ claimText: '' })
        .expect(400);
    });

    it('should reject missing claimText with 400', async () => {
      await request(app.getHttpServer())
        .post(`/sessions/${sessionId}/claims`)
        .send({})
        .expect(400);
    });

    it('should reject unknown properties with 400', async () => {
      await request(app.getHttpServer())
        .post(`/sessions/${sessionId}/claims`)
        .send({ claimText: 'Valid claim', unknownField: 'nope' })
        .expect(400);
    });

    it('should reject claimText exceeding 2000 chars with 400', async () => {
      const longClaim = 'x'.repeat(2001);
      await request(app.getHttpServer())
        .post(`/sessions/${sessionId}/claims`)
        .send({ claimText: longClaim })
        .expect(400);
    });

    it('should reject duplicate claim submission with 409', async () => {
      await request(app.getHttpServer())
        .post(`/sessions/${sessionId}/claims`)
        .send({ claimText: 'First claim' })
        .expect(202);

      await request(app.getHttpServer())
        .post(`/sessions/${sessionId}/claims`)
        .send({ claimText: 'Second claim' })
        .expect(409);
    });

    it('should return 404 for non-existent session', async () => {
      const fakeId = '00000000-0000-4000-a000-000000000000';
      await request(app.getHttpServer())
        .post(`/sessions/${fakeId}/claims`)
        .send({ claimText: 'Some claim' })
        .expect(404);
    });

    it('should reject invalid UUID with 400', async () => {
      await request(app.getHttpServer())
        .post('/sessions/not-a-uuid/claims')
        .send({ claimText: 'Some claim' })
        .expect(400);
    });

    it('should accept optional sourceUrl and sourceDate', async () => {
      const res = await request(app.getHttpServer())
        .post(`/sessions/${sessionId}/claims`)
        .send({
          claimText: 'Claim with metadata',
          sourceUrl: 'https://example.com/article',
          sourceDate: '2026-01-15',
        })
        .expect(202);

      expect(res.body.claim).toBe('Claim with metadata');
    });
  });

  // -----------------------------------------------------------------------
  // GET /sessions/:sessionId — with claim
  // -----------------------------------------------------------------------

  describe('GET /sessions/:sessionId', () => {
    it('should return session details', async () => {
      const createRes = await request(app.getHttpServer())
        .post('/sessions')
        .expect(201);

      const res = await request(app.getHttpServer())
        .get(`/sessions/${createRes.body.sessionId}`)
        .expect(200);

      expect(res.body.sessionId).toBe(createRes.body.sessionId);
      expect(res.body.status).toBe('active');
      expect(res.body.claim).toBeNull();
    });

    it('should reflect the submitted claim', async () => {
      const createRes = await request(app.getHttpServer())
        .post('/sessions')
        .expect(201);

      await request(app.getHttpServer())
        .post(`/sessions/${createRes.body.sessionId}/claims`)
        .send({ claimText: 'Vaccines cause autism' })
        .expect(202);

      const res = await request(app.getHttpServer())
        .get(`/sessions/${createRes.body.sessionId}`)
        .expect(200);

      expect(res.body.claim).toBe('Vaccines cause autism');
    });

    it('should return 404 for non-existent session', async () => {
      const fakeId = '00000000-0000-4000-a000-000000000000';
      await request(app.getHttpServer())
        .get(`/sessions/${fakeId}`)
        .expect(404);
    });

    it('should reject invalid UUID', async () => {
      await request(app.getHttpServer())
        .get('/sessions/not-a-uuid')
        .expect(400);
    });
  });

  // -----------------------------------------------------------------------
  // GET /sessions/:sessionId/verdict — 404 when no verdict
  // -----------------------------------------------------------------------

  describe('GET /sessions/:sessionId/verdict', () => {
    it('should return 404 when session has no verdict', async () => {
      const createRes = await request(app.getHttpServer())
        .post('/sessions')
        .expect(201);

      await request(app.getHttpServer())
        .get(`/sessions/${createRes.body.sessionId}/verdict`)
        .expect(404);
    });

    it('should return 404 for non-existent session', async () => {
      const fakeId = '00000000-0000-4000-a000-000000000000';
      await request(app.getHttpServer())
        .get(`/sessions/${fakeId}/verdict`)
        .expect(404);
    });

    it('should return verdict when one exists', async () => {
      // Seed session, run, verdict, and citation directly
      const session = new Session({
        sessionId: 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee',
        status: SessionStatus.Active,
        claim: 'The earth is flat',
        createdAt: new Date(),
      });
      await sessionRepo.save(session);

      const run = new Run({
        runId: '11111111-2222-4333-8444-555555555555',
        sessionId: session.sessionId,
        status: RunStatus.Completed,
        createdAt: new Date(),
        completedAt: new Date(),
      });
      await runRepo.save(run);

      const verdict = new Verdict({
        verdictId: 'cccccccc-dddd-4eee-8fff-aaaaaaaaaaaa',
        runId: run.runId,
        factualityScore: 0.1,
        ratingLabel: RatingLabel.False,
        narrative: 'The earth is an oblate spheroid.',
        signalCount: 12,
        finalizedAt: new Date(),
      });
      await verdictRepo.save(verdict);

      const citation = new Citation({
        citationId: 'dddddddd-eeee-4fff-8aaa-bbbbbbbbbbbb',
        verdictId: verdict.verdictId,
        sourceUrl: 'https://nasa.gov/earth',
        sourceName: 'NASA',
        agent: 'domain-evidence',
        observationCode: 'DOMAIN_EVIDENCE',
        validationStatus: ValidationStatus.Live,
        convergenceCount: 3,
      });
      await citationRepo.saveMany([citation]);

      streamReader.setObservations([]);

      const res = await request(app.getHttpServer())
        .get(`/sessions/${session.sessionId}/verdict`)
        .expect(200);

      expect(res.body.verdictId).toBe(verdict.verdictId);
      expect(res.body.factualityScore).toBe(0.1);
      expect(res.body.ratingLabel).toBe('false');
      expect(res.body.narrative).toBe('The earth is an oblate spheroid.');
      expect(res.body.signalCount).toBe(12);
      expect(res.body.citations).toHaveLength(1);
      expect(res.body.citations[0].sourceUrl).toBe('https://nasa.gov/earth');
      expect(res.body.citations[0].agent).toBe('domain-evidence');
      expect(res.body.finalizedAt).toBeDefined();
      expect(res.body.coverageBreakdown).toHaveLength(3);
      expect(res.body.blindspotWarnings).toEqual([]);
    });
  });

  // -----------------------------------------------------------------------
  // GET /health
  // -----------------------------------------------------------------------

  describe('GET /health', () => {
    it('should return health status with service checks', async () => {
      // Without TEMPORAL_ADDRESS, Temporal reports unreachable → degraded (503)
      const res = await request(app.getHttpServer()).get('/health');

      expect(res.body).toHaveProperty('status');
      expect(res.body).toHaveProperty('services');
      expect(res.body.services).toHaveProperty('postgresql');
      expect(res.body.services).toHaveProperty('redis');
      expect(res.body.services).toHaveProperty('temporal');
      expect(res.body.services.postgresql).toBe('reachable');
      expect(res.body.services.redis).toBe('reachable');
    });

    it('should return healthy (200) when all services are reachable', async () => {
      // Set TEMPORAL_ADDRESS so Temporal reports reachable
      process.env.TEMPORAL_ADDRESS = 'localhost:7233';
      const res = await request(app.getHttpServer())
        .get('/health')
        .expect(200);

      expect(res.body.status).toBe('healthy');
      expect(res.body.services.temporal).toBe('reachable');
      delete process.env.TEMPORAL_ADDRESS;
    });

    it('should return degraded (503) when some services are unreachable', async () => {
      mockDataSource.shouldFail = true;
      const res = await request(app.getHttpServer())
        .get('/health')
        .expect(503);

      expect(res.body.status).toBe('degraded');
      expect(res.body.services.postgresql).toBe('unreachable');
      mockDataSource.shouldFail = false;
    });
  });

  // -----------------------------------------------------------------------
  // Full claim-to-verdict flow with mocked Temporal
  // -----------------------------------------------------------------------

  describe('Full claim-to-verdict flow', () => {
    it('should complete the entire lifecycle: create → claim → verdict', async () => {
      // 1. Create session
      const sessionRes = await request(app.getHttpServer())
        .post('/sessions')
        .expect(201);
      const sessionId = sessionRes.body.sessionId;

      // 2. Submit claim
      const claimRes = await request(app.getHttpServer())
        .post(`/sessions/${sessionId}/claims`)
        .send({ claimText: 'Water boils at 100°C at sea level' })
        .expect(202);
      expect(claimRes.body.claim).toBe('Water boils at 100°C at sea level');

      // 3. Verify Temporal was invoked
      expect(temporalClient.calls).toHaveLength(1);
      const { runId } = temporalClient.calls[0];

      // 4. Simulate agent completion: insert run, verdict, citations
      const run = await runRepo.findBySessionId(sessionId);
      expect(run).not.toBeNull();

      const verdict = new Verdict({
        verdictId: 'ff000000-0000-4000-8000-000000000001',
        runId: run!.runId,
        factualityScore: 0.95,
        ratingLabel: RatingLabel.True,
        narrative:
          'Water boils at 100°C (212°F) at standard atmospheric pressure (sea level).',
        signalCount: 8,
        finalizedAt: new Date(),
      });
      await verdictRepo.save(verdict);

      await citationRepo.saveMany([
        new Citation({
          citationId: 'ff000000-0000-4000-8000-000000000002',
          verdictId: verdict.verdictId,
          sourceUrl: 'https://www.britannica.com/science/boiling-point',
          sourceName: 'Britannica',
          agent: 'domain-evidence',
          observationCode: 'DOMAIN_EVIDENCE',
          validationStatus: ValidationStatus.Live,
          convergenceCount: 5,
        }),
        new Citation({
          citationId: 'ff000000-0000-4000-8000-000000000003',
          verdictId: verdict.verdictId,
          sourceUrl: 'https://chem.libretexts.org/',
          sourceName: 'LibreTexts',
          agent: 'coverage-center',
          observationCode: 'COVERAGE_TOP_SOURCE_URL',
          validationStatus: ValidationStatus.Live,
          convergenceCount: 2,
        }),
      ]);

      streamReader.setObservations([]);

      // 5. Retrieve verdict
      const verdictRes = await request(app.getHttpServer())
        .get(`/sessions/${sessionId}/verdict`)
        .expect(200);

      expect(verdictRes.body.factualityScore).toBe(0.95);
      expect(verdictRes.body.ratingLabel).toBe('true');
      expect(verdictRes.body.citations).toHaveLength(2);
      expect(verdictRes.body.coverageBreakdown).toHaveLength(3);

      // 6. Session still retrievable with claim
      const getRes = await request(app.getHttpServer())
        .get(`/sessions/${sessionId}`)
        .expect(200);
      expect(getRes.body.claim).toBe('Water boils at 100°C at sea level');
      expect(getRes.body.status).toBe('active');
    });
  });

  // -----------------------------------------------------------------------
  // In-memory TypeORM CRUD
  // -----------------------------------------------------------------------

  describe('Repository CRUD operations', () => {
    it('session: save, findById, delete', async () => {
      const session = new Session({
        sessionId: '00000000-0000-4000-8000-000000000001',
        status: SessionStatus.Active,
        createdAt: new Date(),
      });

      await sessionRepo.save(session);
      const found = await sessionRepo.findById(session.sessionId);
      expect(found).not.toBeNull();
      expect(found!.sessionId).toBe(session.sessionId);

      await sessionRepo.delete(session.sessionId);
      const deleted = await sessionRepo.findById(session.sessionId);
      expect(deleted).toBeNull();
    });

    it('run: save, findById, findBySessionId', async () => {
      const run = new Run({
        runId: '00000000-0000-4000-8000-000000000010',
        sessionId: '00000000-0000-4000-8000-000000000001',
        status: RunStatus.Pending,
        createdAt: new Date(),
      });

      await runRepo.save(run);

      const byId = await runRepo.findById(run.runId);
      expect(byId).not.toBeNull();
      expect(byId!.runId).toBe(run.runId);

      const bySession = await runRepo.findBySessionId(run.sessionId);
      expect(bySession).not.toBeNull();
      expect(bySession!.runId).toBe(run.runId);
    });

    it('verdict: save, findByRunId', async () => {
      const verdict = new Verdict({
        verdictId: '00000000-0000-4000-8000-000000000020',
        runId: '00000000-0000-4000-8000-000000000010',
        factualityScore: 0.75,
        ratingLabel: RatingLabel.MostlyTrue,
        narrative: 'Mostly accurate.',
        signalCount: 5,
        finalizedAt: new Date(),
      });

      await verdictRepo.save(verdict);

      const found = await verdictRepo.findByRunId(verdict.runId);
      expect(found).not.toBeNull();
      expect(found!.factualityScore).toBe(0.75);
    });

    it('verdict: findByRunId returns null when not found', async () => {
      const found = await verdictRepo.findByRunId('nonexistent');
      expect(found).toBeNull();
    });

    it('citation: saveMany, findByVerdictId', async () => {
      const citations = [
        new Citation({
          citationId: '00000000-0000-4000-8000-000000000030',
          verdictId: '00000000-0000-4000-8000-000000000020',
          sourceUrl: 'https://example.com/1',
          sourceName: 'Example 1',
          agent: 'coverage-left',
          observationCode: 'COVERAGE_ARTICLE_COUNT',
          validationStatus: ValidationStatus.Live,
          convergenceCount: 1,
        }),
        new Citation({
          citationId: '00000000-0000-4000-8000-000000000031',
          verdictId: '00000000-0000-4000-8000-000000000020',
          sourceUrl: 'https://example.com/2',
          sourceName: 'Example 2',
          agent: 'coverage-right',
          observationCode: 'COVERAGE_ARTICLE_COUNT',
          validationStatus: ValidationStatus.Dead,
          convergenceCount: 0,
        }),
      ];

      await citationRepo.saveMany(citations);

      const found = await citationRepo.findByVerdictId(
        '00000000-0000-4000-8000-000000000020',
      );
      expect(found).toHaveLength(2);
    });

    it('session: findExpiredSessions', async () => {
      const expired = new Session({
        sessionId: '00000000-0000-4000-8000-000000000099',
        status: SessionStatus.Frozen,
        createdAt: new Date('2024-01-01'),
        frozenAt: new Date('2024-01-02'),
        expiresAt: new Date('2024-01-05'), // in the past
      });
      await sessionRepo.save(expired);

      const active = new Session({
        sessionId: '00000000-0000-4000-8000-000000000098',
        status: SessionStatus.Active,
        createdAt: new Date(),
      });
      await sessionRepo.save(active);

      const expiredSessions = await sessionRepo.findExpiredSessions();
      expect(expiredSessions).toHaveLength(1);
      expect(expiredSessions[0].sessionId).toBe(expired.sessionId);
    });
  });

  // -----------------------------------------------------------------------
  // Verdict presenter coverage breakdown
  // -----------------------------------------------------------------------

  describe('Verdict with coverage observations', () => {
    it('should include coverage breakdown from observations', async () => {
      const session = new Session({
        sessionId: 'bbbbbbbb-0000-4000-8000-000000000001',
        status: SessionStatus.Active,
        claim: 'Test claim',
        createdAt: new Date(),
      });
      await sessionRepo.save(session);

      const run = new Run({
        runId: 'bbbbbbbb-0000-4000-8000-000000000010',
        sessionId: session.sessionId,
        status: RunStatus.Completed,
        createdAt: new Date(),
      });
      await runRepo.save(run);

      const verdict = new Verdict({
        verdictId: 'bbbbbbbb-0000-4000-8000-000000000020',
        runId: run.runId,
        factualityScore: 0.6,
        ratingLabel: RatingLabel.HalfTrue,
        narrative: 'Partially accurate.',
        signalCount: 6,
        finalizedAt: new Date(),
      });
      await verdictRepo.save(verdict);

      streamReader.setObservations([
        {
          agent: 'coverage-left',
          code: 'COVERAGE_ARTICLE_COUNT',
          status: 'F',
          value: '3',
        },
        {
          agent: 'coverage-left',
          code: 'COVERAGE_FRAMING',
          status: 'F',
          value: 'POS^Positive',
        },
        {
          agent: 'coverage-center',
          code: 'COVERAGE_ARTICLE_COUNT',
          status: 'F',
          value: '5',
        },
        {
          agent: 'coverage-center',
          code: 'COVERAGE_FRAMING',
          status: 'F',
          value: 'NEU^Neutral',
        },
        {
          agent: 'coverage-right',
          code: 'COVERAGE_ARTICLE_COUNT',
          status: 'F',
          value: '1',
        },
        {
          agent: 'blindspot-detector',
          code: 'BLINDSPOT_SCORE',
          status: 'F',
          value: '0.7',
        },
        {
          agent: 'blindspot-detector',
          code: 'BLINDSPOT_DIRECTION',
          status: 'F',
          value: 'R^Right-leaning gap',
        },
        {
          agent: 'blindspot-detector',
          code: 'CROSS_SPECTRUM_CORROBORATION',
          status: 'F',
          value: 'TRUE^Corroborated',
        },
      ]);

      const res = await request(app.getHttpServer())
        .get(`/sessions/${session.sessionId}/verdict`)
        .expect(200);

      expect(res.body.coverageBreakdown).toHaveLength(3);

      const left = res.body.coverageBreakdown.find(
        (c: { spectrum: string }) => c.spectrum === 'left',
      );
      expect(left.articleCount).toBe(3);
      expect(left.framing).toBe('Positive');

      const center = res.body.coverageBreakdown.find(
        (c: { spectrum: string }) => c.spectrum === 'center',
      );
      expect(center.articleCount).toBe(5);
      expect(center.framing).toBe('Neutral');

      const right = res.body.coverageBreakdown.find(
        (c: { spectrum: string }) => c.spectrum === 'right',
      );
      expect(right.articleCount).toBe(1);
      expect(right.framing).toBe('Not Covered');

      expect(res.body.blindspotWarnings).toHaveLength(1);
      expect(res.body.blindspotWarnings[0].blindspotScore).toBe(0.7);
      expect(res.body.blindspotWarnings[0].direction).toBe(
        'Right-leaning gap',
      );
      expect(res.body.blindspotWarnings[0].crossSpectrumCorroboration).toBe(
        true,
      );
    });
  });

  // -----------------------------------------------------------------------
  // Edge cases and error handling
  // -----------------------------------------------------------------------

  describe('Error handling', () => {
    it('should reject claim submission to frozen session with 422', async () => {
      const session = new Session({
        sessionId: 'eeeeeeee-0000-4000-8000-000000000001',
        status: SessionStatus.Frozen,
        createdAt: new Date(),
        frozenAt: new Date(),
        expiresAt: new Date(Date.now() + 3 * 24 * 60 * 60 * 1000),
      });
      await sessionRepo.save(session);

      await request(app.getHttpServer())
        .post(`/sessions/${session.sessionId}/claims`)
        .send({ claimText: 'Late claim' })
        .expect(422);
    });
  });
});
