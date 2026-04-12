export interface TemporalClientPort {
  startClaimVerificationWorkflow(
    runId: string,
    sessionId: string,
    claimText: string,
  ): Promise<void>;
  getWorkflowStatus(runId: string): Promise<string>;
  cancelWorkflow(runId: string, reason?: string): Promise<void>;
}

export const TEMPORAL_CLIENT = Symbol('TemporalClient');
