export class ProgressEvent {
  readonly runId: string;
  readonly agent: string;
  readonly phase: string;
  readonly type: 'progress' | 'verdict' | 'close';
  readonly message: string;
  readonly timestamp: Date;

  constructor(params: {
    runId: string;
    agent: string;
    phase: string;
    type: 'progress' | 'verdict' | 'close';
    message: string;
    timestamp: Date;
  }) {
    this.runId = params.runId;
    this.agent = params.agent;
    this.phase = params.phase;
    this.type = params.type;
    this.message = params.message;
    this.timestamp = params.timestamp;
  }
}
