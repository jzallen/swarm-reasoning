import { ProgressPhase } from '../enums/progress-phase.enum';
import { ProgressType } from '../enums/progress-type.enum';

export class ProgressEvent {
  readonly runId: string;
  readonly agent: string;
  readonly phase: ProgressPhase;
  readonly type: ProgressType;
  readonly message: string;
  readonly timestamp: Date;
  readonly entryId: string;

  constructor(params: {
    runId: string;
    agent: string;
    phase: ProgressPhase;
    type: ProgressType;
    message: string;
    timestamp: Date;
    entryId: string;
  }) {
    this.runId = params.runId;
    this.agent = params.agent;
    this.phase = params.phase;
    this.type = params.type;
    this.message = params.message;
    this.timestamp = params.timestamp;
    this.entryId = params.entryId;
  }
}
