import { useEffect, useRef } from 'react';
import type { ProgressEvent } from '@/api/types';
import type { SessionAction, SessionPhase } from './useSession';

interface UseSSEOptions {
  sessionId: string | null;
  phase: SessionPhase;
  dispatch: React.Dispatch<SessionAction>;
  onVerdictReady: (sessionId: string) => void;
}

export function useSSE({ sessionId, phase, dispatch, onVerdictReady }: UseSSEOptions) {
  const sourceRef = useRef<EventSource | null>(null);
  const dispatchRef = useRef(dispatch);
  const onVerdictReadyRef = useRef(onVerdictReady);

  dispatchRef.current = dispatch;
  onVerdictReadyRef.current = onVerdictReady;

  useEffect(() => {
    if (!sessionId || phase !== 'active') return;

    const url = `/sessions/${sessionId}/events`;
    const source = new EventSource(url);
    sourceRef.current = source;

    source.addEventListener('progress', (e: MessageEvent) => {
      try {
        const event = JSON.parse(e.data) as ProgressEvent;
        dispatchRef.current({ type: 'PROGRESS_EVENT', event });
      } catch {
        console.warn('Malformed SSE progress data:', e.data);
      }
    });

    source.addEventListener('verdict', (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as { type: string };
        if (data.type === 'verdict-ready') {
          onVerdictReadyRef.current(sessionId);
        }
      } catch {
        console.warn('Malformed SSE verdict data:', e.data);
      }
    });

    source.addEventListener('close', (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as { type: string; snapshotUrl?: string };
        if (data.type === 'session-frozen') {
          dispatchRef.current({ type: 'SESSION_FROZEN', snapshotUrl: data.snapshotUrl });
        }
      } catch {
        console.warn('Malformed SSE close data:', e.data);
      }
      source.close();
    });

    source.onerror = () => {
      // Native EventSource auto-reconnects with Last-Event-ID.
      // Only log for debugging; do not dispatch error to avoid UI churn.
      if (source.readyState === EventSource.CLOSED) {
        console.warn('SSE connection closed permanently');
      }
    };

    return () => {
      source.close();
      sourceRef.current = null;
    };
  }, [sessionId, phase]);
}
