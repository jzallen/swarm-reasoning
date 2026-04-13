export interface Session {
  sessionId: string;
  status: 'active' | 'frozen' | 'expired';
  claim?: string;
  createdAt: string;
  frozenAt?: string | null;
  expiresAt?: string | null;
  snapshotUrl?: string | null;
}

export interface Claim {
  claimText: string;
  sourceUrl?: string;
  sourceDate?: string;
}

export interface Verdict {
  verdictId: string;
  factualityScore: number;
  ratingLabel: RatingLabel;
  narrative: string;
  signalCount: number;
  citations: Citation[];
  coverageBreakdown: CoverageEntry[];
  blindspotWarnings: BlindspotWarning[];
  finalizedAt: string;
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

export type RatingLabel =
  | 'true'
  | 'mostly-true'
  | 'half-true'
  | 'mostly-false'
  | 'false'
  | 'pants-on-fire';

export interface Citation {
  sourceUrl: string;
  sourceName: string;
  agent: string;
  observationCode: string;
  validationStatus: ValidationStatus;
  convergenceCount: number;
}

export type ValidationStatus =
  | 'live'
  | 'dead'
  | 'redirect'
  | 'soft-404'
  | 'timeout'
  | 'not-validated';

export interface ProgressEvent {
  runId: string;
  agent: string;
  phase: ProgressPhase;
  type: ProgressType;
  message: string;
  timestamp: string;
}

export type ProgressPhase =
  | 'ingestion'
  | 'fanout'
  | 'synthesis'
  | 'finalization';

export type ProgressType =
  | 'agent-started'
  | 'agent-progress'
  | 'agent-completed'
  | 'verdict-ready'
  | 'session-frozen';

export interface ErrorResponse {
  error: string;
  message: string;
}
