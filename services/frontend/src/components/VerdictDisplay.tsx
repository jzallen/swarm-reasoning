import type { Verdict, RatingLabel, CoverageEntry } from '@/api/types';
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

const SPECTRUM_LABELS: Record<CoverageEntry['spectrum'], string> = {
  left: 'Left',
  center: 'Center',
  right: 'Right',
};

const FRAMING_STYLES: Record<string, string> = {
  Supportive: 'framingSupportive',
  Critical: 'framingCritical',
  Neutral: 'framingNeutral',
  'Not Covered': 'framingAbsent',
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

      {verdict.blindspotWarnings.length > 0 && (
        <div className={styles.blindspotBanner}>
          {verdict.blindspotWarnings.map((w, i) => (
            <div key={i} className={styles.blindspotItem}>
              <span className={styles.blindspotIcon}>!</span>
              <span>
                Coverage blindspot detected: <strong>{w.direction}</strong>
                {' '}spectrum underrepresented
                {' '}(asymmetry score: {w.blindspotScore.toFixed(2)})
              </span>
            </div>
          ))}
        </div>
      )}

      {verdict.coverageBreakdown.length > 0 && (
        <div className={styles.coverageSection}>
          <h3 className={styles.sectionTitle}>Coverage Breakdown</h3>
          <div className={styles.coverageGrid}>
            {verdict.coverageBreakdown.map((entry) => (
              <div key={entry.spectrum} className={styles.coverageCard}>
                <span className={styles.spectrumLabel}>
                  {SPECTRUM_LABELS[entry.spectrum]}
                </span>
                <span className={styles.articleCount}>
                  {entry.articleCount} article{entry.articleCount !== 1 ? 's' : ''}
                </span>
                <span
                  className={`${styles.framingBadge} ${
                    styles[FRAMING_STYLES[entry.framing] ?? 'framingNeutral']
                  }`}
                >
                  {entry.framing}
                </span>
                {entry.topSource && (
                  <span className={styles.topSource}>
                    {entry.topSourceUrl ? (
                      <a
                        href={entry.topSourceUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {entry.topSource}
                      </a>
                    ) : (
                      entry.topSource
                    )}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {verdict.citations.length > 0 && (
        <CitationTable citations={verdict.citations} />
      )}

      <PrintButton />
    </div>
  );
}
