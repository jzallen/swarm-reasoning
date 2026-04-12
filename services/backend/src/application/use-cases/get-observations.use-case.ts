import { Inject, Injectable, NotFoundException } from '@nestjs/common';
import { SESSION_REPOSITORY } from '../interfaces/session.repository.js';
import { RUN_REPOSITORY } from '../interfaces/run.repository.js';
import { STREAM_READER } from '../interfaces/stream-reader.interface.js';
import * as SessionRepo from '../interfaces/session.repository.js';
import * as RunRepo from '../interfaces/run.repository.js';
import * as StreamInt from '../interfaces/stream-reader.interface.js';

@Injectable()
export class GetObservationsUseCase {
  constructor(
    @Inject(SESSION_REPOSITORY)
    private readonly sessionRepository: SessionRepo.SessionRepository,
    @Inject(RUN_REPOSITORY)
    private readonly runRepository: RunRepo.RunRepository,
    @Inject(STREAM_READER)
    private readonly streamReader: StreamInt.StreamReader,
  ) {}

  async execute(sessionId: string): Promise<Record<string, unknown>[]> {
    const session = await this.sessionRepository.findById(sessionId);
    if (!session) {
      throw new NotFoundException(`Session ${sessionId} not found`);
    }

    const run = await this.runRepository.findBySessionId(sessionId);
    if (!run) {
      throw new NotFoundException(`No run found for session ${sessionId}`);
    }

    return this.streamReader.readObservations(run.runId);
  }
}
