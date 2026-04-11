import { Injectable } from '@nestjs/common';
import { Verdict, Citation } from '../../domain/entities';

export interface VerdictResponse {
  verdictId: string;
  factualityScore: number;
  ratingLabel: string;
  narrative: string;
  signalCount: number;
  citations: CitationResponse[];
  finalizedAt: string;
}

export interface CitationResponse {
  sourceUrl: string;
  sourceName: string;
  agent: string;
  observationCode: string;
  validationStatus: string;
  convergenceCount: number;
}

@Injectable()
export class VerdictPresenter {
  format(verdict: Verdict, citations: Citation[]): VerdictResponse {
    return {
      verdictId: verdict.verdictId,
      factualityScore: verdict.factualityScore,
      ratingLabel: verdict.ratingLabel,
      narrative: verdict.narrative,
      signalCount: verdict.signalCount,
      citations: citations.map((c) => ({
        sourceUrl: c.sourceUrl,
        sourceName: c.sourceName,
        agent: c.agent,
        observationCode: c.observationCode,
        validationStatus: c.validationStatus,
        convergenceCount: c.convergenceCount,
      })),
      finalizedAt: verdict.finalizedAt.toISOString(),
    };
  }
}
