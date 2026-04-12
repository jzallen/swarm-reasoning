export interface TemporalClientPort {
  startClaimVerificationWorkflow(
    runId: string,
    sessionId: string,
    claimText: string,
  ): Promise<void>;
  getWorkflowStatus(runId: string): Promise<string>;
}

export const TEMPORAL_CLIENT = Symbol('TemporalClient');
