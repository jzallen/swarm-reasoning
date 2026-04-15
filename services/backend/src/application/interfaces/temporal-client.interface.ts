export interface TemporalClientPort {
  startClaimVerificationWorkflow(
    runId: string,
    sessionId: string,
    claimText: string,
    claimUrl?: string,
    submissionDate?: string,
  ): Promise<void>;
  getWorkflowStatus(runId: string): Promise<string>;
  cancelWorkflow(runId: string, reason?: string): Promise<void>;
}

export const TEMPORAL_CLIENT = Symbol('TemporalClient');
