import {
  Injectable,
  Logger,
  OnModuleInit,
  OnModuleDestroy,
} from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import {
  Connection,
  WorkflowClient,
  WorkflowNotFoundError,
} from '@temporalio/client';
import { TemporalClientPort } from '@app/interfaces';

const TASK_QUEUE = 'claim-verification';
const WORKFLOW_TYPE = 'ClaimVerificationWorkflow';

@Injectable()
export class TemporalClientAdapter
  implements TemporalClientPort, OnModuleInit, OnModuleDestroy
{
  private readonly logger = new Logger(TemporalClientAdapter.name);
  private readonly temporalAddress: string;
  private connection!: Connection;
  private client!: WorkflowClient;

  constructor(private readonly configService: ConfigService) {
    this.temporalAddress = this.configService.get<string>(
      'TEMPORAL_ADDRESS',
      'localhost:7233',
    );
  }

  async onModuleInit(): Promise<void> {
    this.connection = await Connection.connect({
      address: this.temporalAddress,
    });
    this.client = new WorkflowClient({ connection: this.connection });
    this.logger.log(`Connected to Temporal at ${this.temporalAddress}`);
  }

  async onModuleDestroy(): Promise<void> {
    await this.connection?.close();
    this.logger.log('Temporal connection closed');
  }

  async startClaimVerificationWorkflow(
    runId: string,
    sessionId: string,
    claimText: string,
    claimUrl?: string,
    submissionDate?: string,
  ): Promise<void> {
    await this.client.start(WORKFLOW_TYPE, {
      workflowId: `claim-verification-${runId}`,
      taskQueue: TASK_QUEUE,
      args: [{ runId, sessionId, claimText, claimUrl, submissionDate }],
    });
    this.logger.log(
      `Started workflow claim-verification-${runId} for session ${sessionId}`,
    );
  }

  async getWorkflowStatus(runId: string): Promise<string> {
    try {
      const handle = this.client.getHandle(`claim-verification-${runId}`);
      const description = await handle.describe();
      return description.status.name;
    } catch (error) {
      if (error instanceof WorkflowNotFoundError) {
        return 'NOT_FOUND';
      }
      throw error;
    }
  }

  async cancelWorkflow(runId: string, reason?: string): Promise<void> {
    const handle = this.client.getHandle(`claim-verification-${runId}`);
    await handle.cancel();
    this.logger.log(
      `Cancelled workflow claim-verification-${runId}: ${reason ?? 'User requested cancellation'}`,
    );
  }
}
