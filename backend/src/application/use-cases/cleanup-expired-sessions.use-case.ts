import { Inject, Injectable, Logger } from '@nestjs/common';
import { SESSION_REPOSITORY } from '../interfaces/session.repository.js';
import { SNAPSHOT_STORE } from '../interfaces/snapshot-store.interface.js';
import * as SessionRepo from '../interfaces/session.repository.js';
import * as SnapshotInt from '../interfaces/snapshot-store.interface.js';

@Injectable()
export class CleanupExpiredSessionsUseCase {
  private readonly logger = new Logger(CleanupExpiredSessionsUseCase.name);

  constructor(
    @Inject(SESSION_REPOSITORY)
    private readonly sessionRepository: SessionRepo.SessionRepository,
    @Inject(SNAPSHOT_STORE)
    private readonly snapshotStore: SnapshotInt.SnapshotStore,
  ) {}

  async execute(): Promise<number> {
    const expired = await this.sessionRepository.findExpiredSessions();
    let cleaned = 0;

    for (const session of expired) {
      try {
        if (session.snapshotUrl) {
          await this.snapshotStore.delete(session.snapshotUrl);
        }
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
