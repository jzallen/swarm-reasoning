import { Inject, Injectable } from '@nestjs/common';
import { v4 as uuidv4 } from 'uuid';
import { Session } from '@domain/entities/session.entity.js';
import { SessionStatus } from '@domain/enums/index.js';
import { SESSION_REPOSITORY } from '../interfaces/session.repository.js';
import * as SessionRepo from '../interfaces/session.repository.js';

@Injectable()
export class CreateSessionUseCase {
  constructor(
    @Inject(SESSION_REPOSITORY)
    private readonly sessionRepository: SessionRepo.SessionRepository,
  ) {}

  async execute(): Promise<Session> {
    const session = new Session({
      sessionId: uuidv4(),
      status: SessionStatus.Active,
      createdAt: new Date(),
    });
    return this.sessionRepository.save(session);
  }
}
