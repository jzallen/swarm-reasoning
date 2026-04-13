import { Inject, Injectable, Logger, NotFoundException } from '@nestjs/common';
import { Verdict } from '@domain/entities/verdict.entity.js';
import { Citation } from '@domain/entities/citation.entity.js';
import { ProgressEvent } from '@domain/entities/progress-event.entity.js';
import { SessionStatus } from '@domain/enums/index.js';
import { SESSION_REPOSITORY } from '../interfaces/session.repository.js';
import { VERDICT_REPOSITORY } from '../interfaces/verdict.repository.js';
import { CITATION_REPOSITORY } from '../interfaces/citation.repository.js';
import { SNAPSHOT_STORE } from '../interfaces/snapshot-store.interface.js';
import { STREAM_READER } from '../interfaces/stream-reader.interface.js';
import { HTML_RENDERER } from '../interfaces/html-renderer.interface.js';
import * as SessionRepo from '../interfaces/session.repository.js';
import * as VerdictRepo from '../interfaces/verdict.repository.js';
import * as CitationRepo from '../interfaces/citation.repository.js';
import * as SnapshotInt from '../interfaces/snapshot-store.interface.js';
import * as StreamInt from '../interfaces/stream-reader.interface.js';
import * as HtmlRendererInt from '../interfaces/html-renderer.interface.js';

@Injectable()
export class FinalizeSessionUseCase {
  private readonly logger = new Logger(FinalizeSessionUseCase.name);

  constructor(
    @Inject(SESSION_REPOSITORY)
    private readonly sessionRepository: SessionRepo.SessionRepository,
    @Inject(VERDICT_REPOSITORY)
    private readonly verdictRepository: VerdictRepo.VerdictRepository,
    @Inject(CITATION_REPOSITORY)
    private readonly citationRepository: CitationRepo.CitationRepository,
    @Inject(SNAPSHOT_STORE)
    private readonly snapshotStore: SnapshotInt.SnapshotStore,
    @Inject(STREAM_READER)
    private readonly streamReader: StreamInt.StreamReader,
    @Inject(HTML_RENDERER)
    private readonly htmlRenderer: HtmlRendererInt.HtmlRenderer,
  ) {}

  async execute(
    sessionId: string,
    verdict: Verdict,
    citations: Citation[],
    runId: string,
  ): Promise<void> {
    const startTime = Date.now();

    const session = await this.sessionRepository.findById(sessionId);
    if (!session) {
      throw new NotFoundException(`Session ${sessionId} not found`);
    }

    await this.verdictRepository.save(verdict);
    await this.citationRepository.saveMany(citations);

    // Read progress events from Redis stream for the chat view
    const progressEvents = await this.collectProgressEvents(runId);

    session.transitionTo(SessionStatus.Frozen);

    const html = this.htmlRenderer.render(
      verdict,
      citations,
      session,
      progressEvents,
    );
    const snapshotUrl = await this.snapshotStore.upload(sessionId, html);
    session.snapshotUrl = snapshotUrl;

    await this.sessionRepository.save(session);

    const renderDuration = Date.now() - startTime;
    this.logger.log(`Session ${sessionId} finalized in ${renderDuration}ms`);
  }

  private async collectProgressEvents(runId: string): Promise<ProgressEvent[]> {
    try {
      return await this.streamReader.readAllProgressEvents(runId);
    } catch {
      this.logger.warn(`Failed to read progress events for run ${runId}`);
      return [];
    }
  }
}
