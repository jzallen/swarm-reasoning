import { NotFoundException } from '@nestjs/common';
import { FinalizeSessionUseCase } from '../use-cases/finalize-session.use-case';
import { Session, Verdict, Citation, ProgressEvent } from '../../domain/entities';
import {
  SessionStatus,
  RatingLabel,
  ValidationStatus,
  ProgressPhase,
  ProgressType,
} from '../../domain/enums';

function makeMocks() {
  const mockSessionRepo = {
    save: jest.fn().mockResolvedValue(undefined),
    findById: jest.fn(),
    findExpiredSessions: jest.fn(),
    delete: jest.fn(),
  };

  const mockVerdictRepo = {
    save: jest.fn().mockResolvedValue(undefined),
    findByRunId: jest.fn(),
  };

  const mockCitationRepo = {
    saveMany: jest.fn().mockResolvedValue(undefined),
    findByVerdictId: jest.fn(),
  };

  const mockSnapshotStore = {
    upload: jest.fn().mockResolvedValue('https://snapshots.example.com/s1.html'),
    delete: jest.fn(),
  };

  const mockStreamReader = {
    readProgress: jest.fn(),
    readObservations: jest.fn(),
    readAllProgressEvents: jest.fn().mockResolvedValue([]),
    deleteStreams: jest.fn(),
    ping: jest.fn(),
  };

  const mockHtmlRenderer = {
    render: jest.fn().mockReturnValue('<html>snapshot</html>'),
  };

  return {
    mockSessionRepo,
    mockVerdictRepo,
    mockCitationRepo,
    mockSnapshotStore,
    mockStreamReader,
    mockHtmlRenderer,
  };
}

const activeSession = () =>
  new Session({
    sessionId: 'session-1',
    status: SessionStatus.Active,
    claim: 'The earth is round',
    createdAt: new Date(),
  });

const sampleVerdict = () =>
  new Verdict({
    verdictId: 'verdict-1',
    runId: 'run-1',
    factualityScore: 0.95,
    ratingLabel: RatingLabel.True,
    narrative: 'Supported by scientific consensus.',
    signalCount: 8,
    finalizedAt: new Date(),
  });

const sampleCitations = () => [
  new Citation({
    citationId: 'cit-1',
    verdictId: 'verdict-1',
    sourceUrl: 'https://nasa.gov/earth',
    sourceName: 'NASA',
    agent: 'domain-evidence',
    observationCode: 'DE-001',
    validationStatus: ValidationStatus.Live,
    convergenceCount: 3,
  }),
  new Citation({
    citationId: 'cit-2',
    verdictId: 'verdict-1',
    sourceUrl: 'https://example.com/article',
    sourceName: 'Example News',
    agent: 'coverage-center',
    observationCode: 'CC-001',
    validationStatus: ValidationStatus.Live,
    convergenceCount: 2,
  }),
];

const sampleProgressEvents = () => [
  new ProgressEvent({
    runId: 'run-1',
    agent: 'ingestion-agent',
    phase: ProgressPhase.Ingestion,
    type: ProgressType.AgentCompleted,
    message: 'Ingestion complete',
    timestamp: new Date(),
    entryId: '1-0',
  }),
];

describe('FinalizeSessionUseCase', () => {
  it('should save verdict, citations, snapshot and freeze the session', async () => {
    const mocks = makeMocks();
    const session = activeSession();
    mocks.mockSessionRepo.findById.mockResolvedValue(session);

    const useCase = new FinalizeSessionUseCase(
      mocks.mockSessionRepo,
      mocks.mockVerdictRepo,
      mocks.mockCitationRepo,
      mocks.mockSnapshotStore,
      mocks.mockStreamReader,
      mocks.mockHtmlRenderer,
    );

    const verdict = sampleVerdict();
    const citations = sampleCitations();

    await useCase.execute('session-1', verdict, citations, 'run-1');

    expect(mocks.mockVerdictRepo.save).toHaveBeenCalledWith(verdict);
    expect(mocks.mockCitationRepo.saveMany).toHaveBeenCalledWith(citations);
    expect(session.status).toBe(SessionStatus.Frozen);
    expect(session.frozenAt).toBeInstanceOf(Date);
    expect(session.expiresAt).toBeInstanceOf(Date);
    expect(session.snapshotUrl).toBe(
      'https://snapshots.example.com/s1.html',
    );
    expect(mocks.mockHtmlRenderer.render).toHaveBeenCalledWith(
      verdict,
      citations,
      session,
      [],
    );
    expect(mocks.mockSnapshotStore.upload).toHaveBeenCalledWith(
      'session-1',
      '<html>snapshot</html>',
    );
    expect(mocks.mockSessionRepo.save).toHaveBeenCalledWith(session);
  });

  it('should throw NotFoundException when session does not exist', async () => {
    const mocks = makeMocks();
    mocks.mockSessionRepo.findById.mockResolvedValue(null);

    const useCase = new FinalizeSessionUseCase(
      mocks.mockSessionRepo,
      mocks.mockVerdictRepo,
      mocks.mockCitationRepo,
      mocks.mockSnapshotStore,
      mocks.mockStreamReader,
      mocks.mockHtmlRenderer,
    );

    await expect(
      useCase.execute('missing', sampleVerdict(), sampleCitations(), 'run-1'),
    ).rejects.toThrow(NotFoundException);

    expect(mocks.mockVerdictRepo.save).not.toHaveBeenCalled();
    expect(mocks.mockCitationRepo.saveMany).not.toHaveBeenCalled();
    expect(mocks.mockSessionRepo.save).not.toHaveBeenCalled();
  });

  it('should pass progress events from stream reader to html renderer', async () => {
    const mocks = makeMocks();
    const session = activeSession();
    const events = sampleProgressEvents();
    mocks.mockSessionRepo.findById.mockResolvedValue(session);
    mocks.mockStreamReader.readAllProgressEvents.mockResolvedValue(events);

    const useCase = new FinalizeSessionUseCase(
      mocks.mockSessionRepo,
      mocks.mockVerdictRepo,
      mocks.mockCitationRepo,
      mocks.mockSnapshotStore,
      mocks.mockStreamReader,
      mocks.mockHtmlRenderer,
    );

    const verdict = sampleVerdict();
    const citations = sampleCitations();

    await useCase.execute('session-1', verdict, citations, 'run-1');

    expect(mocks.mockStreamReader.readAllProgressEvents).toHaveBeenCalledWith(
      'run-1',
    );
    expect(mocks.mockHtmlRenderer.render).toHaveBeenCalledWith(
      verdict,
      citations,
      session,
      events,
    );
  });

  it('should use empty progress events when stream reader fails', async () => {
    const mocks = makeMocks();
    const session = activeSession();
    mocks.mockSessionRepo.findById.mockResolvedValue(session);
    mocks.mockStreamReader.readAllProgressEvents.mockRejectedValue(
      new Error('Redis connection lost'),
    );

    const useCase = new FinalizeSessionUseCase(
      mocks.mockSessionRepo,
      mocks.mockVerdictRepo,
      mocks.mockCitationRepo,
      mocks.mockSnapshotStore,
      mocks.mockStreamReader,
      mocks.mockHtmlRenderer,
    );

    const verdict = sampleVerdict();
    const citations = sampleCitations();

    await useCase.execute('session-1', verdict, citations, 'run-1');

    // Should still succeed with empty events fallback
    expect(mocks.mockHtmlRenderer.render).toHaveBeenCalledWith(
      verdict,
      citations,
      session,
      [],
    );
    expect(session.status).toBe(SessionStatus.Frozen);
    expect(session.snapshotUrl).toBe(
      'https://snapshots.example.com/s1.html',
    );
  });

  it('should work with an empty citations array', async () => {
    const mocks = makeMocks();
    const session = activeSession();
    mocks.mockSessionRepo.findById.mockResolvedValue(session);

    const useCase = new FinalizeSessionUseCase(
      mocks.mockSessionRepo,
      mocks.mockVerdictRepo,
      mocks.mockCitationRepo,
      mocks.mockSnapshotStore,
      mocks.mockStreamReader,
      mocks.mockHtmlRenderer,
    );

    await useCase.execute('session-1', sampleVerdict(), [], 'run-1');

    expect(mocks.mockCitationRepo.saveMany).toHaveBeenCalledWith([]);
    expect(mocks.mockSessionRepo.save).toHaveBeenCalled();
  });

  it('should set session expiresAt to 3 days after frozenAt', async () => {
    const mocks = makeMocks();
    const session = activeSession();
    mocks.mockSessionRepo.findById.mockResolvedValue(session);

    const useCase = new FinalizeSessionUseCase(
      mocks.mockSessionRepo,
      mocks.mockVerdictRepo,
      mocks.mockCitationRepo,
      mocks.mockSnapshotStore,
      mocks.mockStreamReader,
      mocks.mockHtmlRenderer,
    );

    await useCase.execute('session-1', sampleVerdict(), [], 'run-1');

    const threeDaysMs = 3 * 24 * 60 * 60 * 1000;
    const diff = session.expiresAt!.getTime() - session.frozenAt!.getTime();
    expect(diff).toBe(threeDaysMs);
  });
});
