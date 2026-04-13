import { Inject, Injectable, NotFoundException } from '@nestjs/common';
import { Verdict } from '@domain/entities/verdict.entity.js';
import { Citation } from '@domain/entities/citation.entity.js';
import { SESSION_REPOSITORY } from '../interfaces/session.repository.js';
import { RUN_REPOSITORY } from '../interfaces/run.repository.js';
import { VERDICT_REPOSITORY } from '../interfaces/verdict.repository.js';
import { CITATION_REPOSITORY } from '../interfaces/citation.repository.js';
import { STREAM_READER } from '../interfaces/stream-reader.interface.js';
import * as SessionRepo from '../interfaces/session.repository.js';
import * as RunRepo from '../interfaces/run.repository.js';
import * as VerdictRepo from '../interfaces/verdict.repository.js';
import * as CitationRepo from '../interfaces/citation.repository.js';
import * as StreamInt from '../interfaces/stream-reader.interface.js';

export interface VerdictWithCitations {
  verdict: Verdict;
  citations: Citation[];
  observations: Record<string, unknown>[];
}

@Injectable()
export class GetVerdictUseCase {
  constructor(
    @Inject(SESSION_REPOSITORY)
    private readonly sessionRepository: SessionRepo.SessionRepository,
    @Inject(RUN_REPOSITORY)
    private readonly runRepository: RunRepo.RunRepository,
    @Inject(VERDICT_REPOSITORY)
    private readonly verdictRepository: VerdictRepo.VerdictRepository,
    @Inject(CITATION_REPOSITORY)
    private readonly citationRepository: CitationRepo.CitationRepository,
    @Inject(STREAM_READER)
    private readonly streamReader: StreamInt.StreamReader,
  ) {}

  async execute(sessionId: string): Promise<VerdictWithCitations> {
    const session = await this.sessionRepository.findById(sessionId);
    if (!session) {
      throw new NotFoundException(`Session ${sessionId} not found`);
    }

    const run = await this.runRepository.findBySessionId(sessionId);
    if (!run) {
      throw new NotFoundException(`No run found for session ${sessionId}`);
    }

    const verdict = await this.verdictRepository.findByRunId(run.runId);
    if (!verdict) {
      throw new NotFoundException(`No verdict found for session ${sessionId}`);
    }

    const [citations, observations] = await Promise.all([
      this.citationRepository.findByVerdictId(verdict.verdictId),
      this.streamReader.readObservations(run.runId),
    ]);

    return { verdict, citations, observations };
  }
}
