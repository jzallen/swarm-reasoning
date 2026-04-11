import { NotFoundException, GoneException } from '@nestjs/common';
import { StreamProgressUseCase } from '../use-cases/stream-progress.use-case';
import { SessionStatus, ProgressPhase, ProgressType } from '../../domain/enums';
import { Session } from '../../domain/entities/session.entity';
import { ProgressEvent } from '../../domain/entities/progress-event.entity';

function makeSession(status: SessionStatus): Session {
  return new Session({
    sessionId: 'sess-1',
    status,
    createdAt: new Date(),
  });
}

function makeProgressEvent(
  type: ProgressType = ProgressType.AgentProgress,
): ProgressEvent {
  return new ProgressEvent({
    runId: 'run-1',
    agent: 'ingestion-agent',
    phase: ProgressPhase.Ingestion,
    type,
    message: 'Processing claim',
    timestamp: new Date(),
    entryId: '1712736005000-0',
  });
}

describe('StreamProgressUseCase', () => {
  const mockSessionRepo = {
    findById: jest.fn(),
    save: jest.fn(),
    findExpiredSessions: jest.fn(),
    delete: jest.fn(),
  };

  const mockRunRepo = {
    findBySessionId: jest.fn(),
    save: jest.fn(),
    findById: jest.fn(),
  };

  async function* fakeStream(): AsyncGenerator<ProgressEvent> {
    yield makeProgressEvent();
  }

  const mockStreamReader = {
    readProgress: jest.fn(() => fakeStream()),
    readObservations: jest.fn(),
  };

  let useCase: StreamProgressUseCase;

  beforeEach(() => {
    jest.clearAllMocks();
    useCase = new StreamProgressUseCase(
      mockSessionRepo,
      mockRunRepo,
      mockStreamReader,
    );
  });

  it('should throw NotFoundException when session not found', async () => {
    mockSessionRepo.findById.mockResolvedValue(null);

    const gen = useCase.execute('missing-session');
    await expect(gen.next()).rejects.toThrow(NotFoundException);
  });

  it('should throw GoneException when session is expired', async () => {
    mockSessionRepo.findById.mockResolvedValue(
      makeSession(SessionStatus.Expired),
    );

    const gen = useCase.execute('sess-1');
    await expect(gen.next()).rejects.toThrow(GoneException);
  });

  it('should throw NotFoundException when no run found', async () => {
    mockSessionRepo.findById.mockResolvedValue(
      makeSession(SessionStatus.Active),
    );
    mockRunRepo.findBySessionId.mockResolvedValue(null);

    const gen = useCase.execute('sess-1');
    await expect(gen.next()).rejects.toThrow(NotFoundException);
  });

  it('should yield progress events for active session', async () => {
    mockSessionRepo.findById.mockResolvedValue(
      makeSession(SessionStatus.Active),
    );
    mockRunRepo.findBySessionId.mockResolvedValue({ runId: 'run-1' });

    const gen = useCase.execute('sess-1');
    const result = await gen.next();

    expect(result.done).toBe(false);
    expect(result.value).toBeInstanceOf(ProgressEvent);
    expect(result.value?.type).toBe(ProgressType.AgentProgress);
  });

  it('should pass lastEventId to stream reader', async () => {
    mockSessionRepo.findById.mockResolvedValue(
      makeSession(SessionStatus.Active),
    );
    mockRunRepo.findBySessionId.mockResolvedValue({ runId: 'run-1' });

    const gen = useCase.execute('sess-1', '1712736005000-0');
    await gen.next();

    expect(mockStreamReader.readProgress).toHaveBeenCalledWith(
      'run-1',
      '1712736005000-0',
    );
  });

  it('should stream frozen sessions for replay', async () => {
    mockSessionRepo.findById.mockResolvedValue(
      makeSession(SessionStatus.Frozen),
    );
    mockRunRepo.findBySessionId.mockResolvedValue({ runId: 'run-1' });

    const gen = useCase.execute('sess-1');
    const result = await gen.next();

    expect(result.done).toBe(false);
    expect(result.value).toBeInstanceOf(ProgressEvent);
  });
});
