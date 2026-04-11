import { Inject, Injectable, Logger } from '@nestjs/common';
import { SESSION_REPOSITORY } from '../interfaces/session.repository.js';
import { SNAPSHOT_STORE } from '../interfaces/snapshot-store.interface.js';
import { RUN_REPOSITORY } from '../interfaces/run.repository.js';
import { STREAM_READER } from '../interfaces/stream-reader.interface.js';
import * as SessionRepo from '../interfaces/session.repository.js';
import * as SnapshotInt from '../interfaces/snapshot-store.interface.js';
import * as RunRepo from '../interfaces/run.repository.js';
import * as StreamInt from '../interfaces/stream-reader.interface.js';

@Injectable()
export class CleanupExpiredSessionsUseCase {
  private readonly logger = new Logger(CleanupExpiredSessionsUseCase.name);

  constructor(
    @Inject(SESSION_REPOSITORY)
    private readonly sessionRepository: SessionRepo.SessionRepository,
    @Inject(SNAPSHOT_STORE)
    private readonly snapshotStore: SnapshotInt.SnapshotStore,
    @Inject(RUN_REPOSITORY)
    private readonly runRepository: RunRepo.RunRepository,
    @Inject(STREAM_READER)
    private readonly streamReader: StreamInt.StreamReader,
  ) {}

  async execute(): Promise<number> {
    const expired = await this.sessionRepository.findExpiredSessions();
    let cleaned = 0;

    for (const session of expired) {
      try {
        // Delete snapshot file/object
        if (session.snapshotUrl) {
          await this.snapshotStore.delete(session.snapshotUrl);
        }

        // Delete Redis streams (progress + reasoning)
        const run = await this.runRepository.findBySessionId(session.sessionId);
        if (run) {
          await this.streamReader.deleteStreams(run.runId);
        }

        // Delete database rows (cascade: citations, verdict, session)
        await this.sessionRepository.delete(session.sessionId);
        cleaned++;
      } catch (error) {
        this.logger.error(
          `Failed to clean up session ${session.sessionId}: ${error}`,
        );
      }
    }

    if (cleaned > 0) {
      this.logger.log(`Cleaned up ${cleaned} expired sessions`);
    }
    return cleaned;
  }
}
