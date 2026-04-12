import { ValidationStatus } from '../enums';

export class Citation {
  readonly citationId: string;
  readonly verdictId: string;
  readonly sourceUrl: string;
  readonly sourceName: string;
  readonly agent: string;
  readonly observationCode: string;
  readonly validationStatus: ValidationStatus;
  readonly convergenceCount: number;

  constructor(params: {
    citationId: string;
    verdictId: string;
    sourceUrl: string;
    sourceName: string;
    agent: string;
    observationCode: string;
    validationStatus: ValidationStatus;
    convergenceCount: number;
  }) {
    this.citationId = params.citationId;
    this.verdictId = params.verdictId;
    this.sourceUrl = params.sourceUrl;
    this.sourceName = params.sourceName;
    this.agent = params.agent;
    this.observationCode = params.observationCode;
    this.validationStatus = params.validationStatus;
    this.convergenceCount = params.convergenceCount;
  }
}
