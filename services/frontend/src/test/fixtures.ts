import type { Citation, ProgressEvent, Verdict } from '@/api/types';

export function makeCitation(overrides: Partial<Citation> = {}): Citation {
  return {
    sourceUrl: 'https://example.com/article',
    sourceName: 'Example Source',
    agent: 'source-validator',
    observationCode: 'SRC-001',
    validationStatus: 'live',
    convergenceCount: 3,
    ...overrides,
  };
}

export function makeProgressEvent(overrides: Partial<ProgressEvent> = {}): ProgressEvent {
  return {
    runId: 'run-001',
    agent: 'ingestion-agent',
    phase: 'ingestion',
    type: 'agent-progress',
    message: 'Processing claim...',
    timestamp: '2026-04-13T12:00:00Z',
    ...overrides,
  };
}

export function makeVerdict(overrides: Partial<Verdict> = {}): Verdict {
  return {
    verdictId: 'v-001',
    factualityScore: 0.85,
    ratingLabel: 'mostly-true',
    narrative: 'The claim is mostly accurate with minor inaccuracies.',
    signalCount: 42,
    citations: [makeCitation()],
    finalizedAt: '2026-04-13T12:05:00Z',
    ...overrides,
  };
}
