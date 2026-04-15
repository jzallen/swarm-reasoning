import styles from './PrintButton.module.css';

export function PrintButton() {
  return (
    <button
      className={styles.btn}
      onClick={() => window.print()}
      type="button"
    >
      Print
    </button>
  );
}
