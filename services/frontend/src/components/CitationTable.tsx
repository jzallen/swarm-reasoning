import type { Citation, ValidationStatus } from '@/api/types';
import styles from './CitationTable.module.css';

const STATUS_CONFIG: Record<ValidationStatus, { label: string; className: string }> = {
  'live': { label: 'Live', className: 'statusGreen' },
  'dead': { label: 'Dead', className: 'statusRed' },
  'redirect': { label: 'Redirect', className: 'statusYellow' },
  'soft-404': { label: 'Soft 404', className: 'statusYellow' },
  'timeout': { label: 'Timeout', className: 'statusYellow' },
  'not-validated': { label: 'Not Validated', className: 'statusGray' },
};

interface CitationTableProps {
  citations: Citation[];
}

export function CitationTable({ citations }: CitationTableProps) {
  const sorted = [...citations].sort((a, b) => b.convergenceCount - a.convergenceCount);

  return (
    <div className={styles.wrapper}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Source</th>
            <th>URL</th>
            <th>Agent</th>
            <th>Code</th>
            <th>Status</th>
            <th>Cited By</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((c, i) => {
            const status = STATUS_CONFIG[c.validationStatus];
            return (
              <tr key={`${c.sourceUrl}-${i}`}>
                <td data-label="Source">{c.sourceName}</td>
                <td data-label="URL">
                  <a
                    href={c.sourceUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={styles.link}
                  >
                    {truncateUrl(c.sourceUrl)}
                  </a>
                </td>
                <td data-label="Agent">{c.agent}</td>
                <td data-label="Code" className={styles.code}>{c.observationCode}</td>
                <td data-label="Status">
                  <span className={`${styles.statusDot} ${styles[status.className]}`} />
                  {status.label}
                </td>
                <td data-label="Cited By" className={styles.count}>{c.convergenceCount}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function truncateUrl(url: string, maxLen = 40): string {
  if (url.length <= maxLen) return url;
  return url.slice(0, maxLen - 1) + '\u2026';
}
