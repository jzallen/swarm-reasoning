import { ProgressType } from '@domain/enums/progress-type.enum';

export type SseEventName = 'progress' | 'verdict' | 'close';

const TYPE_TO_SSE_EVENT: Record<ProgressType, SseEventName> = {
  [ProgressType.AgentStarted]: 'progress',
  [ProgressType.AgentProgress]: 'progress',
  [ProgressType.AgentCompleted]: 'progress',
  [ProgressType.VerdictReady]: 'verdict',
  [ProgressType.SessionFrozen]: 'close',
};

export function mapProgressTypeToSseEvent(type: ProgressType): SseEventName {
  return TYPE_TO_SSE_EVENT[type];
}

export function isTerminalEvent(type: ProgressType): boolean {
  return (
    type === ProgressType.VerdictReady ||
    type === ProgressType.SessionFrozen
  );
}
