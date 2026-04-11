import { useSession } from '@/hooks/useSession';
import { useSSE } from '@/hooks/useSSE';
import { ChatInterface } from '@/components/ChatInterface';
import { VerdictDisplay } from '@/components/VerdictDisplay';
import { SnapshotView } from '@/components/SnapshotView';
import { ErrorBanner } from '@/components/ErrorBanner';
import styles from './App.module.css';

export default function App() {
  const { state, dispatch, handleSubmit, handleVerdictReady } = useSession();

  useSSE({
    sessionId: state.sessionId,
    phase: state.phase,
    dispatch,
    onVerdictReady: handleVerdictReady,
  });

  return (
    <div className={styles.layout}>
      <header className={styles.header}>
        <h1 className={styles.title}>Swarm Reasoning</h1>
        <span className={styles.subtitle}>Multi-Agent Fact Checker</span>
      </header>

      <main className={styles.main}>
        {state.phase === 'error' && state.error && (
          <ErrorBanner message={state.error} />
        )}

        {state.phase === 'expired' && (
          <SnapshotView snapshotUrl={null} isExpired />
        )}

        {state.phase === 'frozen' && (
          <SnapshotView snapshotUrl={state.snapshotUrl} />
        )}

        {(state.phase === 'idle' || state.phase === 'creating' || state.phase === 'active' || state.phase === 'verdict') && (
          <>
            <ChatInterface
              phase={state.phase}
              claim={state.claim}
              events={state.events}
              onSubmit={handleSubmit}
            />

            {state.phase === 'verdict' && state.verdict && (
              <VerdictDisplay verdict={state.verdict} />
            )}
          </>
        )}
      </main>
    </div>
  );
}
