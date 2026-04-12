import { RatingLabel } from '../enums';

export class Verdict {
  readonly verdictId: string;
  readonly runId: string;
  readonly factualityScore: number;
  readonly ratingLabel: RatingLabel;
  readonly narrative: string;
  readonly signalCount: number;
  readonly finalizedAt: Date;

  constructor(params: {
    verdictId: string;
    runId: string;
    factualityScore: number;
    ratingLabel: RatingLabel;
    narrative: string;
    signalCount: number;
    finalizedAt: Date;
  }) {
    if (params.factualityScore < 0 || params.factualityScore > 1) {
      throw new Error('Factuality score must be between 0.0 and 1.0');
    }
    this.verdictId = params.verdictId;
    this.runId = params.runId;
    this.factualityScore = params.factualityScore;
    this.ratingLabel = params.ratingLabel;
    this.narrative = params.narrative;
    this.signalCount = params.signalCount;
    this.finalizedAt = params.finalizedAt;
  }
}
