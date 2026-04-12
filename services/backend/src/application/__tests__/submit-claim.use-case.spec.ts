import { NotFoundException } from '@nestjs/common';
import { SubmitClaimUseCase } from '../use-cases/submit-claim.use-case';
import { Session } from '../../domain/entities';
import { SessionStatus } from '../../domain/enums';

describe('SubmitClaimUseCase', () => {
  const mockSession = new Session({
    sessionId: 'test-id',
    status: SessionStatus.Active,
    createdAt: new Date(),
  });

  const createMocks = (session: Session | null = mockSession) => ({
    sessionRepo: {
      save: jest.fn((s) => Promise.resolve(s)),
      findById: jest.fn().mockResolvedValue(session),
      findExpiredSessions: jest.fn(),
      delete: jest.fn(),
    },
    runRepo: {
      save: jest.fn((r) => Promise.resolve(r)),
      findById: jest.fn(),
      findBySessionId: jest.fn(),
    },
    temporalClient: {
      startClaimVerificationWorkflow: jest.fn().mockResolvedValue(undefined),
      getWorkflowStatus: jest.fn(),
    },
  });

  it('should submit claim, create run, and start workflow', async () => {
    const mocks = createMocks();
    const useCase = new SubmitClaimUseCase(
      mocks.sessionRepo,
      mocks.runRepo,
      mocks.temporalClient,
    );

    const result = await useCase.execute('test-id', {
      claimText: 'Test claim',
    });

    expect(result.claim).toBe('Test claim');
    expect(mocks.runRepo.save).toHaveBeenCalledTimes(1);
    expect(mocks.sessionRepo.save).toHaveBeenCalledTimes(1);
    expect(
      mocks.temporalClient.startClaimVerificationWorkflow,
    ).toHaveBeenCalledTimes(1);
  });

  it('should throw NotFoundException for missing session', async () => {
    const mocks = createMocks(null);
    const useCase = new SubmitClaimUseCase(
      mocks.sessionRepo,
      mocks.runRepo,
      mocks.temporalClient,
    );

    await expect(
      useCase.execute('missing', { claimText: 'Test' }),
    ).rejects.toThrow(NotFoundException);
  });
});
