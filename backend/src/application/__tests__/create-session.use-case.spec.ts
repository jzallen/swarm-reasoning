import { CreateSessionUseCase } from '../use-cases/create-session.use-case';
import { SessionStatus } from '../../domain/enums';

describe('CreateSessionUseCase', () => {
  it('should create a session with active status and UUID', async () => {
    const mockRepo = {
      save: jest.fn((session) => Promise.resolve(session)),
      findById: jest.fn(),
      findExpiredSessions: jest.fn(),
      delete: jest.fn(),
    };

    const useCase = new CreateSessionUseCase(mockRepo);
    const session = await useCase.execute();

    expect(session.sessionId).toBeDefined();
    expect(session.sessionId).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
    );
    expect(session.status).toBe(SessionStatus.Active);
    expect(session.createdAt).toBeInstanceOf(Date);
    expect(mockRepo.save).toHaveBeenCalledTimes(1);
  });
});
