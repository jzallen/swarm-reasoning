import type { Verdict, RatingLabel } from '@/api/types';
import { CitationTable } from './CitationTable';
import { PrintButton } from './PrintButton';
import styles from './VerdictDisplay.module.css';

const RATING_CONFIG: Record<RatingLabel, { text: string; className: string }> = {
  'true': { text: 'True', className: 'ratingGreen' },
  'mostly-true': { text: 'Mostly True', className: 'ratingGreen' },
  'half-true': { text: 'Half True', className: 'ratingYellow' },
  'mostly-false': { text: 'Mostly False', className: 'ratingOrange' },
  'false': { text: 'False', className: 'ratingRed' },
  'pants-on-fire': { text: 'Pants on Fire', className: 'ratingRed' },
};

interface VerdictDisplayProps {
  verdict: Verdict;
}

export function VerdictDisplay({ verdict }: VerdictDisplayProps) {
  const ratingCfg = RATING_CONFIG[verdict.ratingLabel];

  return (
    <div className={styles.card}>
      <div className={styles.header}>
        <div className={styles.scoreBlock}>
          <span className={styles.score}>
            {verdict.factualityScore.toFixed(2)}
          </span>
          <span className={styles.scoreLabel}>Factuality Score</span>
        </div>
        <span className={`${styles.ratingBadge} ${styles[ratingCfg.className]}`}>
          {ratingCfg.text}
        </span>
      </div>

      <p className={styles.narrative}>{verdict.narrative}</p>

      <p className={styles.signalCount}>
        Based on {verdict.signalCount} signals from 11 agents
      </p>

      {verdict.citations.length > 0 && (
        <CitationTable citations={verdict.citations} />
      )}

      <PrintButton />
    </div>
  );
}
