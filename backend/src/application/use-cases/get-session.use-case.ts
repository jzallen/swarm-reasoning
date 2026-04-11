import { Inject, Injectable, NotFoundException } from '@nestjs/common';
import { Session } from '../../domain/entities/session.entity.js';
import { SESSION_REPOSITORY } from '../interfaces/session.repository.js';
import * as SessionRepo from '../interfaces/session.repository.js';

@Injectable()
export class GetSessionUseCase {
  constructor(
    @Inject(SESSION_REPOSITORY)
    private readonly sessionRepository: SessionRepo.SessionRepository,
  ) {}

  async execute(sessionId: string): Promise<Session> {
    const session = await this.sessionRepository.findById(sessionId);
    if (!session) {
      throw new NotFoundException(`Session ${sessionId} not found`);
    }
    return session;
  }
}
