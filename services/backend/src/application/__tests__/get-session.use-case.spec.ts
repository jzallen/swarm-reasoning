import { NotFoundException } from '@nestjs/common';
import { GetSessionUseCase } from '../use-cases/get-session.use-case';
import { Session } from '../../domain/entities';
import { SessionStatus } from '../../domain/enums';

describe('GetSessionUseCase', () => {
  const mockSession = new Session({
    sessionId: 'test-id',
    status: SessionStatus.Active,
    createdAt: new Date(),
  });

  it('should return session when found', async () => {
    const mockRepo = {
      save: jest.fn(),
      findById: jest.fn().mockResolvedValue(mockSession),
      findExpiredSessions: jest.fn(),
      delete: jest.fn(),
    };

    const useCase = new GetSessionUseCase(mockRepo);
    const result = await useCase.execute('test-id');
    expect(result.sessionId).toBe('test-id');
  });

  it('should throw NotFoundException when not found', async () => {
    const mockRepo = {
      save: jest.fn(),
      findById: jest.fn().mockResolvedValue(null),
      findExpiredSessions: jest.fn(),
      delete: jest.fn(),
    };

    const useCase = new GetSessionUseCase(mockRepo);
    await expect(useCase.execute('missing')).rejects.toThrow(
      NotFoundException,
    );
  });
});
