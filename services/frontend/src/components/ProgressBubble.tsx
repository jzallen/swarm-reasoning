import type { ProgressEvent, ProgressPhase, ProgressType } from '@/api/types';
import styles from './ProgressBubble.module.css';

const PHASE_LABELS: Record<ProgressPhase, string> = {
  ingestion: 'Ingestion',
  fanout: 'Fanout',
  synthesis: 'Synthesis',
  finalization: 'Finalization',
};

function formatTime(timestamp: string): string {
  const d = new Date(timestamp);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function isLifecycleEvent(type: ProgressType): boolean {
  return type === 'agent-started' || type === 'agent-completed';
}

interface ProgressBubbleProps {
  event: ProgressEvent;
}

export function ProgressBubble({ event }: ProgressBubbleProps) {
  const lifecycle = isLifecycleEvent(event.type);
  const phaseClass = styles[`phase_${event.phase}`] ?? '';

  return (
    <div className={`${styles.bubble} ${lifecycle ? styles.lifecycle : ''}`}>
      <div className={styles.header}>
        <span className={styles.agent}>{event.agent}</span>
        <span className={`${styles.badge} ${phaseClass}`}>
          {PHASE_LABELS[event.phase] ?? event.phase}
        </span>
        <span className={styles.time}>{formatTime(event.timestamp)}</span>
      </div>
      <p className={styles.message}>{event.message}</p>
    </div>
  );
}
