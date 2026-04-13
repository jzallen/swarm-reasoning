import {
  ConflictException,
  Inject,
  Injectable,
  NotFoundException,
  UnprocessableEntityException,
} from '@nestjs/common';
import { v4 as uuidv4 } from 'uuid';
import { Session } from '@domain/entities/session.entity.js';
import { Run } from '@domain/entities/run.entity.js';
import { Claim } from '@domain/value-objects/claim.js';
import { RunStatus, SessionStatus } from '@domain/enums/index.js';
import { SESSION_REPOSITORY } from '../interfaces/session.repository.js';
import { RUN_REPOSITORY } from '../interfaces/run.repository.js';
import { TEMPORAL_CLIENT } from '../interfaces/temporal-client.interface.js';
import * as SessionRepo from '../interfaces/session.repository.js';
import * as RunRepo from '../interfaces/run.repository.js';
import * as TemporalPort from '../interfaces/temporal-client.interface.js';

@Injectable()
export class SubmitClaimUseCase {
  constructor(
    @Inject(SESSION_REPOSITORY)
    private readonly sessionRepository: SessionRepo.SessionRepository,
    @Inject(RUN_REPOSITORY)
    private readonly runRepository: RunRepo.RunRepository,
    @Inject(TEMPORAL_CLIENT)
    private readonly temporalClient: TemporalPort.TemporalClientPort,
  ) {}

  async execute(
    sessionId: string,
    claimData: { claimText: string; sourceUrl?: string; sourceDate?: string },
  ): Promise<Session> {
    const session = await this.sessionRepository.findById(sessionId);
    if (!session) {
      throw new NotFoundException(`Session ${sessionId} not found`);
    }

    if (session.status !== SessionStatus.Active) {
      throw new UnprocessableEntityException('Session is no longer active');
    }

    if (session.claim) {
      throw new ConflictException('Session already has a claim submitted');
    }

    const claim = new Claim(claimData);
    session.claim = claim.claimText;

    const run = new Run({
      runId: uuidv4(),
      sessionId: session.sessionId,
      status: RunStatus.Pending,
      createdAt: new Date(),
    });

    await this.runRepository.save(run);
    await this.sessionRepository.save(session);

    try {
      await this.temporalClient.startClaimVerificationWorkflow(
        run.runId,
        session.sessionId,
        claim.claimText,
      );
    } catch (error) {
      run.transitionTo(RunStatus.Failed);
      await this.runRepository.save(run);
      throw error;
    }

    return session;
  }
}
