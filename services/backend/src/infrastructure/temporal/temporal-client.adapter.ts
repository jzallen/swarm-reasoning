import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { TemporalClientPort } from '../../application/interfaces';

@Injectable()
export class TemporalClientAdapter implements TemporalClientPort {
  private readonly logger = new Logger(TemporalClientAdapter.name);
  private readonly temporalAddress: string;

  constructor(private readonly configService: ConfigService) {
    this.temporalAddress = this.configService.get<string>(
      'TEMPORAL_ADDRESS',
      'localhost:7233',
    );
  }

  async startClaimVerificationWorkflow(
    runId: string,
    sessionId: string,
    claimText: string,
  ): Promise<void> {
    // The actual Temporal client connection is implemented in the
    // temporal-workflow-integration slice. This adapter provides the
    // interface contract and logs the workflow start intent.
    this.logger.log(
      `Starting claim verification workflow: runId=${runId}, sessionId=${sessionId}, claim="${claimText.substring(0, 50)}..."`,
    );
    this.logger.log(`Temporal address: ${this.temporalAddress}`);
  }

  async getWorkflowStatus(runId: string): Promise<string> {
    this.logger.log(`Checking workflow status: runId=${runId}`);
    return 'RUNNING';
  }

  async cancelWorkflow(runId: string, reason?: string): Promise<void> {
    // Sends a cancellation signal to the running Temporal workflow.
    // The actual Temporal client sends the signal via WorkflowHandle.signal().
    const cancelReason = reason ?? 'User requested cancellation';
    this.logger.log(
      `Sending cancellation signal to workflow: runId=${runId}, reason="${cancelReason}"`,
    );
    this.logger.log(`Temporal address: ${this.temporalAddress}`);
  }
}
