import { CleanupExpiredSessionsUseCase } from '../use-cases/cleanup-expired-sessions.use-case';
import { Session } from '../../domain/entities';
import { SessionStatus } from '../../domain/enums';

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

    const mockSessionRepo = {
      save: jest.fn(),
      findById: jest.fn(),
      findExpiredSessions: jest.fn().mockResolvedValue(expired),
      delete: jest.fn().mockResolvedValue(undefined),
    };

    const mockSnapshotStore = {
      upload: jest.fn(),
      delete: jest.fn().mockResolvedValue(undefined),
    };

    const useCase = new CleanupExpiredSessionsUseCase(
      mockSessionRepo,
      mockSnapshotStore,
    );

    const count = await useCase.execute();

    expect(count).toBe(2);
    expect(mockSnapshotStore.delete).toHaveBeenCalledTimes(1);
    expect(mockSnapshotStore.delete).toHaveBeenCalledWith(
      '/snapshots/s1.html',
    );
    expect(mockSessionRepo.delete).toHaveBeenCalledTimes(2);
  });

  it('should return 0 when no expired sessions', async () => {
    const mockSessionRepo = {
      save: jest.fn(),
      findById: jest.fn(),
      findExpiredSessions: jest.fn().mockResolvedValue([]),
      delete: jest.fn(),
    };

    const mockSnapshotStore = {
      upload: jest.fn(),
      delete: jest.fn(),
    };

    const useCase = new CleanupExpiredSessionsUseCase(
      mockSessionRepo,
      mockSnapshotStore,
    );

    const count = await useCase.execute();
    expect(count).toBe(0);
  });
});
