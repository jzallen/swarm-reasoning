import styles from './ErrorBanner.module.css';

interface ErrorBannerProps {
  message: string;
  onDismiss: () => void;
  onRetry: () => void;
}

export function ErrorBanner({ message, onDismiss, onRetry }: ErrorBannerProps) {
  return (
    <div className={styles.banner} role="alert">
      <p className={styles.text}>{message}</p>
      <div className={styles.actions}>
        <button className={styles.retryBtn} onClick={onRetry}>
          Try again
        </button>
        <button className={styles.dismissBtn} onClick={onDismiss}>
          Dismiss
        </button>
      </div>
    </div>
  );
}
