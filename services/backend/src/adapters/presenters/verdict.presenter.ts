import { Injectable } from '@nestjs/common';
import { Verdict, Citation } from '@domain/entities';

export interface VerdictResponse {
  verdictId: string;
  factualityScore: number;
  ratingLabel: string;
  narrative: string;
  signalCount: number;
  citations: CitationResponse[];
  coverageBreakdown: CoverageEntry[];
  blindspotWarnings: BlindspotWarning[];
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

export interface CoverageEntry {
  spectrum: 'left' | 'center' | 'right';
  articleCount: number;
  framing: string;
  topSource: string | null;
  topSourceUrl: string | null;
}

export interface BlindspotWarning {
  blindspotScore: number;
  direction: string;
  crossSpectrumCorroboration: boolean;
}

const COVERAGE_AGENTS = ['coverage-left', 'coverage-center', 'coverage-right'];
const SPECTRUM_MAP: Record<string, 'left' | 'center' | 'right'> = {
  'coverage-left': 'left',
  'coverage-center': 'center',
  'coverage-right': 'right',
};

@Injectable()
export class VerdictPresenter {
  format(
    verdict: Verdict,
    citations: Citation[],
    observations: Record<string, unknown>[] = [],
  ): VerdictResponse {
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
      coverageBreakdown: this.buildCoverageBreakdown(observations),
      blindspotWarnings: this.buildBlindspotWarnings(observations),
      finalizedAt: verdict.finalizedAt.toISOString(),
    };
  }

  private buildCoverageBreakdown(
    observations: Record<string, unknown>[],
  ): CoverageEntry[] {
    const finalObs = observations.filter((o) => o.status === 'F');
    const entries: CoverageEntry[] = [];

    for (const agent of COVERAGE_AGENTS) {
      const agentObs = finalObs.filter((o) => o.agent === agent);
      const articleCountObs = agentObs.find(
        (o) => o.code === 'COVERAGE_ARTICLE_COUNT',
      );
      const framingObs = agentObs.find((o) => o.code === 'COVERAGE_FRAMING');
      const topSourceObs = agentObs.find(
        (o) => o.code === 'COVERAGE_TOP_SOURCE',
      );
      const topSourceUrlObs = agentObs.find(
        (o) => o.code === 'COVERAGE_TOP_SOURCE_URL',
      );

      entries.push({
        spectrum: SPECTRUM_MAP[agent],
        articleCount: articleCountObs ? Number(articleCountObs.value) : 0,
        framing: framingObs
          ? this.extractCodedDisplay(String(framingObs.value))
          : 'Not Covered',
        topSource: topSourceObs ? String(topSourceObs.value) : null,
        topSourceUrl: topSourceUrlObs ? String(topSourceUrlObs.value) : null,
      });
    }

    return entries;
  }

  private buildBlindspotWarnings(
    observations: Record<string, unknown>[],
  ): BlindspotWarning[] {
    const finalObs = observations.filter(
      (o) => o.status === 'F' && o.agent === 'blindspot-detector',
    );

    const scoreObs = finalObs.find((o) => o.code === 'BLINDSPOT_SCORE');
    const directionObs = finalObs.find((o) => o.code === 'BLINDSPOT_DIRECTION');
    const corrobObs = finalObs.find(
      (o) => o.code === 'CROSS_SPECTRUM_CORROBORATION',
    );

    if (!scoreObs) return [];

    const direction = directionObs
      ? this.extractCodedDisplay(String(directionObs.value))
      : 'Unknown';

    if (direction === 'No Blindspot') return [];

    return [
      {
        blindspotScore: Number(scoreObs.value),
        direction,
        crossSpectrumCorroboration: corrobObs
          ? String(corrobObs.value).startsWith('TRUE')
          : false,
      },
    ];
  }

  private extractCodedDisplay(coded: string): string {
    const parts = coded.split('^');
    return parts.length >= 2 ? parts[1] : coded;
  }
}
