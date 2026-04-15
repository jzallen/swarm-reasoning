import { RunStatus } from '../enums';

const VALID_TRANSITIONS: Record<RunStatus, RunStatus[]> = {
  // Pending can go to Ingesting (phased) or directly to Completed (simplified pipeline)
  [RunStatus.Pending]: [
    RunStatus.Ingesting,
    RunStatus.Completed,
    RunStatus.Cancelled,
    RunStatus.Failed,
  ],
  [RunStatus.Ingesting]: [
    RunStatus.Analyzing,
    RunStatus.Completed,
    RunStatus.Cancelled,
    RunStatus.Failed,
  ],
  [RunStatus.Analyzing]: [
    RunStatus.Synthesizing,
    RunStatus.Completed,
    RunStatus.Cancelled,
    RunStatus.Failed,
  ],
  [RunStatus.Synthesizing]: [
    RunStatus.Completed,
    RunStatus.Cancelled,
    RunStatus.Failed,
  ],
  [RunStatus.Completed]: [],
  [RunStatus.Cancelled]: [],
  [RunStatus.Failed]: [],
};

export class Run {
  readonly runId: string;
  readonly sessionId: string;
  status: RunStatus;
  phase?: string;
  readonly createdAt: Date;
  completedAt?: Date;

  constructor(params: {
    runId: string;
    sessionId: string;
    status: RunStatus;
    phase?: string;
    createdAt: Date;
    completedAt?: Date;
  }) {
    this.runId = params.runId;
    this.sessionId = params.sessionId;
    this.status = params.status;
    this.phase = params.phase;
    this.createdAt = params.createdAt;
    this.completedAt = params.completedAt;
  }

  transitionTo(newStatus: RunStatus): void {
    const allowed = VALID_TRANSITIONS[this.status];
    if (!allowed.includes(newStatus)) {
      throw new Error(`Invalid run transition: ${this.status} -> ${newStatus}`);
    }
    this.status = newStatus;
    if (
      newStatus === RunStatus.Completed ||
      newStatus === RunStatus.Cancelled ||
      newStatus === RunStatus.Failed
    ) {
      this.completedAt = new Date();
    }
  }
}
