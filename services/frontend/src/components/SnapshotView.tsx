import { PrintButton } from './PrintButton';
import styles from './SnapshotView.module.css';

interface SnapshotViewProps {
  snapshotUrl: string | null;
  isExpired?: boolean;
}

export function SnapshotView({ snapshotUrl, isExpired }: SnapshotViewProps) {
  if (isExpired) {
    return (
      <div className={styles.expired}>
        <p>This session has expired. Results are retained for 3 days.</p>
      </div>
    );
  }

  if (!snapshotUrl) {
    return (
      <div className={styles.fallback}>
        <p>Snapshot is not yet available. The session has been frozen but the snapshot is still being generated.</p>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      <div className={styles.toolbar}>
        <PrintButton />
      </div>
      <iframe
        className={styles.iframe}
        src={snapshotUrl}
        title="Session snapshot"
      />
    </div>
  );
}
