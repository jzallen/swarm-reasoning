import { CleanupExpiredSessionsUseCase } from '../use-cases/cleanup-expired-sessions.use-case';
import { Session } from '../../domain/entities';
import { SessionStatus } from '../../domain/enums';

function makeMocks() {
  const mockSessionRepo = {
    save: jest.fn(),
    findById: jest.fn(),
    findExpiredSessions: jest.fn().mockResolvedValue([]),
    delete: jest.fn().mockResolvedValue(undefined),
  };

  const mockSnapshotStore = {
    upload: jest.fn(),
    delete: jest.fn().mockResolvedValue(undefined),
  };

  const mockRunRepo = {
    save: jest.fn(),
    findById: jest.fn(),
    findBySessionId: jest.fn().mockResolvedValue({ runId: 'run-1' }),
  };

  const mockStreamReader = {
    readProgress: jest.fn(),
    readObservations: jest.fn(),
    readAllProgressEvents: jest.fn().mockResolvedValue([]),
    deleteStreams: jest.fn().mockResolvedValue(undefined),
  };

  return { mockSessionRepo, mockSnapshotStore, mockRunRepo, mockStreamReader };
}

describe('CleanupExpiredSessionsUseCase', () => {
  it('should delete expired sessions and their snapshots', async () => {
    const expired = [
      new Session({
        sessionId: 's1',
        status: SessionStatus.Frozen,
        createdAt: new Date(),
        snapshotUrl: '/snapshots/s1.html',
        expiresAt: new Date(Date.now() - 1000),
      }),
      new Session({
        sessionId: 's2',
        status: SessionStatus.Frozen,
        createdAt: new Date(),
        expiresAt: new Date(Date.now() - 1000),
      }),
    ];

    const {
      mockSessionRepo,
      mockSnapshotStore,
      mockRunRepo,
      mockStreamReader,
    } = makeMocks();
    mockSessionRepo.findExpiredSessions.mockResolvedValue(expired);

    const useCase = new CleanupExpiredSessionsUseCase(
      mockSessionRepo,
      mockSnapshotStore,
      mockRunRepo,
      mockStreamReader,
    );

    const count = await useCase.execute();

    expect(count).toBe(2);
    expect(mockSnapshotStore.delete).toHaveBeenCalledTimes(1);
    expect(mockSnapshotStore.delete).toHaveBeenCalledWith('/snapshots/s1.html');
    expect(mockSessionRepo.delete).toHaveBeenCalledTimes(2);
    expect(mockStreamReader.deleteStreams).toHaveBeenCalledTimes(2);
    expect(mockStreamReader.deleteStreams).toHaveBeenCalledWith('run-1');
  });

  it('should return 0 when no expired sessions', async () => {
    const {
      mockSessionRepo,
      mockSnapshotStore,
      mockRunRepo,
      mockStreamReader,
    } = makeMocks();

    const useCase = new CleanupExpiredSessionsUseCase(
      mockSessionRepo,
      mockSnapshotStore,
      mockRunRepo,
      mockStreamReader,
    );

    const count = await useCase.execute();
    expect(count).toBe(0);
  });

  it('should continue cleanup when one session fails', async () => {
    const expired = [
      new Session({
        sessionId: 's1',
        status: SessionStatus.Frozen,
        createdAt: new Date(),
        snapshotUrl: '/snapshots/s1.html',
        expiresAt: new Date(Date.now() - 1000),
      }),
      new Session({
        sessionId: 's2',
        status: SessionStatus.Frozen,
        createdAt: new Date(),
        expiresAt: new Date(Date.now() - 1000),
      }),
    ];

    const {
      mockSessionRepo,
      mockSnapshotStore,
      mockRunRepo,
      mockStreamReader,
    } = makeMocks();
    mockSessionRepo.findExpiredSessions.mockResolvedValue(expired);
    mockSnapshotStore.delete.mockRejectedValueOnce(new Error('S3 error'));

    const useCase = new CleanupExpiredSessionsUseCase(
      mockSessionRepo,
      mockSnapshotStore,
      mockRunRepo,
      mockStreamReader,
    );

    const count = await useCase.execute();

    // s1 fails (snapshot delete throws), s2 succeeds
    expect(count).toBe(1);
  });
});
