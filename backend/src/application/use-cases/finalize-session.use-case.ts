import { Inject, Injectable, NotFoundException } from '@nestjs/common';
import { Verdict } from '../../domain/entities/verdict.entity.js';
import { Citation } from '../../domain/entities/citation.entity.js';
import { SessionStatus } from '../../domain/enums/index.js';
import { SESSION_REPOSITORY } from '../interfaces/session.repository.js';
import { VERDICT_REPOSITORY } from '../interfaces/verdict.repository.js';
import { CITATION_REPOSITORY } from '../interfaces/citation.repository.js';
import { SNAPSHOT_STORE } from '../interfaces/snapshot-store.interface.js';
import * as SessionRepo from '../interfaces/session.repository.js';
import * as VerdictRepo from '../interfaces/verdict.repository.js';
import * as CitationRepo from '../interfaces/citation.repository.js';
import * as SnapshotInt from '../interfaces/snapshot-store.interface.js';

@Injectable()
export class FinalizeSessionUseCase {
  constructor(
    @Inject(SESSION_REPOSITORY)
    private readonly sessionRepository: SessionRepo.SessionRepository,
    @Inject(VERDICT_REPOSITORY)
    private readonly verdictRepository: VerdictRepo.VerdictRepository,
    @Inject(CITATION_REPOSITORY)
    private readonly citationRepository: CitationRepo.CitationRepository,
    @Inject(SNAPSHOT_STORE)
    private readonly snapshotStore: SnapshotInt.SnapshotStore,
  ) {}

  async execute(
    sessionId: string,
    verdict: Verdict,
    citations: Citation[],
  ): Promise<void> {
    const session = await this.sessionRepository.findById(sessionId);
    if (!session) {
      throw new NotFoundException(`Session ${sessionId} not found`);
    }

    await this.verdictRepository.save(verdict);
    await this.citationRepository.saveMany(citations);

    session.transitionTo(SessionStatus.Frozen);

    const html = this.renderStaticHtml(session, verdict, citations);
    const snapshotUrl = await this.snapshotStore.upload(sessionId, html);
    session.snapshotUrl = snapshotUrl;

    await this.sessionRepository.save(session);
  }

  private renderStaticHtml(
    session: { sessionId: string; claim?: string },
    verdict: Verdict,
    citations: Citation[],
  ): string {
    const citationRows = citations
      .map(
        (c) =>
          `<tr><td>${c.sourceName}</td><td>${c.agent}</td><td>${c.observationCode}</td><td>${c.validationStatus}</td><td>${c.convergenceCount}</td><td><a href="${c.sourceUrl}">${c.sourceUrl}</a></td></tr>`,
      )
      .join('\n');

    return `<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Verdict: ${session.sessionId}</title>
<style>body{font-family:system-ui,sans-serif;max-width:800px;margin:2rem auto;padding:0 1rem}
table{border-collapse:collapse;width:100%}th,td{border:1px solid #ddd;padding:8px;text-align:left}
th{background:#f5f5f5}.score{font-size:2rem;font-weight:bold}.label{font-size:1.2rem;color:#555}</style>
</head>
<body>
<h1>Fact-Check Verdict</h1>
<p><strong>Claim:</strong> ${session.claim ?? 'N/A'}</p>
<p class="score">${verdict.factualityScore.toFixed(2)}</p>
<p class="label">${verdict.ratingLabel}</p>
<h2>Narrative</h2>
<p>${verdict.narrative}</p>
<p><strong>Signals:</strong> ${verdict.signalCount}</p>
<h2>Citations</h2>
<table><thead><tr><th>Source</th><th>Agent</th><th>Code</th><th>Status</th><th>Convergence</th><th>URL</th></tr></thead>
<tbody>${citationRows}</tbody></table>
<footer><p>Session ${session.sessionId} &mdash; Finalized ${verdict.finalizedAt.toISOString()}</p></footer>
</body></html>`;
  }
}
