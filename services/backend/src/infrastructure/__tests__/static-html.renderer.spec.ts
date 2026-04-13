import { StaticHtmlRenderer } from '../renderers/static-html.renderer';
import { Verdict } from '@domain/entities/verdict.entity';
import { Citation } from '@domain/entities/citation.entity';
import { Session } from '@domain/entities/session.entity';
import { ProgressEvent } from '@domain/entities/progress-event.entity';
import {
  RatingLabel,
  SessionStatus,
  ValidationStatus,
  ProgressPhase,
  ProgressType,
} from '@domain/enums';

function makeVerdict(
  overrides: Partial<ConstructorParameters<typeof Verdict>[0]> = {},
): Verdict {
  return new Verdict({
    verdictId: 'v-1',
    runId: 'run-1',
    factualityScore: 0.85,
    ratingLabel: RatingLabel.MostlyTrue,
    narrative: 'The claim is mostly supported by evidence.',
    signalCount: 12,
    finalizedAt: new Date('2026-01-15T10:00:00Z'),
    ...overrides,
  });
}

function makeSession(
  overrides: Partial<ConstructorParameters<typeof Session>[0]> = {},
): Session {
  return new Session({
    sessionId: 'sess-1',
    status: SessionStatus.Frozen,
    claim: 'The unemployment rate is at a historic low.',
    createdAt: new Date('2026-01-15T09:00:00Z'),
    ...overrides,
  });
}

function makeCitation(
  overrides: Partial<ConstructorParameters<typeof Citation>[0]> = {},
): Citation {
  return new Citation({
    citationId: 'cit-1',
    verdictId: 'v-1',
    sourceUrl: 'https://bls.gov/data',
    sourceName: 'Bureau of Labor Statistics',
    agent: 'domain-evidence',
    observationCode: 'DOMAIN_SOURCE_URL',
    validationStatus: ValidationStatus.Live,
    convergenceCount: 3,
    ...overrides,
  });
}

function makeEvent(
  overrides: Partial<ConstructorParameters<typeof ProgressEvent>[0]> = {},
): ProgressEvent {
  return new ProgressEvent({
    runId: 'run-1',
    agent: 'ingestion-agent',
    phase: ProgressPhase.Ingestion,
    type: ProgressType.AgentProgress,
    message: 'Processing claim...',
    timestamp: new Date('2026-01-15T09:01:00Z'),
    entryId: '1-0',
    ...overrides,
  });
}

describe('StaticHtmlRenderer', () => {
  let renderer: StaticHtmlRenderer;

  beforeEach(() => {
    renderer = new StaticHtmlRenderer();
  });

  it('should render valid HTML5 document', () => {
    const html = renderer.render(
      makeVerdict(),
      [makeCitation()],
      makeSession(),
      [makeEvent()],
    );

    expect(html).toContain('<!DOCTYPE html>');
    expect(html).toContain('<html lang="en">');
    expect(html).toContain('<meta charset="utf-8">');
    expect(html).toContain('<meta name="viewport"');
    expect(html).toContain('</html>');
  });

  it('should include both verdict and chat sections', () => {
    const html = renderer.render(makeVerdict(), [], makeSession(), []);

    expect(html).toContain('id="verdict"');
    expect(html).toContain('id="chat"');
  });

  it('should include tab bar with toggle buttons', () => {
    const html = renderer.render(makeVerdict(), [], makeSession(), []);

    expect(html).toContain('class="tab-bar"');
    expect(html).toContain("switchTab('verdict')");
    expect(html).toContain("switchTab('chat')");
    expect(html).toContain('Verdict');
    expect(html).toContain('Agent Progress');
  });

  it('should include inline script for tab toggle', () => {
    const html = renderer.render(makeVerdict(), [], makeSession(), []);

    expect(html).toContain('<script>');
    expect(html).toContain('function switchTab');
    expect(html).toContain('</script>');
  });

  it('should include all CSS in a style block', () => {
    const html = renderer.render(makeVerdict(), [], makeSession(), []);

    expect(html).toContain('<style>');
    expect(html).toContain('</style>');
    // No external stylesheet references
    expect(html).not.toContain('<link rel="stylesheet"');
    expect(html).not.toContain('<script src=');
  });

  it('should render verdict data correctly', () => {
    const html = renderer.render(makeVerdict(), [], makeSession(), []);

    expect(html).toContain('85%'); // score percentage
    expect(html).toContain('mostly-true'); // rating label
    expect(html).toContain('The claim is mostly supported by evidence.'); // narrative
    expect(html).toContain('12 signals analyzed'); // signal count
    expect(html).toContain('The unemployment rate is at a historic low.'); // claim
  });

  it('should render citations sorted by convergence count descending', () => {
    const cit1 = makeCitation({
      citationId: 'c1',
      convergenceCount: 1,
      sourceName: 'Low Source',
    });
    const cit2 = makeCitation({
      citationId: 'c2',
      convergenceCount: 5,
      sourceName: 'High Source',
    });
    const cit3 = makeCitation({
      citationId: 'c3',
      convergenceCount: 3,
      sourceName: 'Mid Source',
    });

    const html = renderer.render(
      makeVerdict(),
      [cit1, cit2, cit3],
      makeSession(),
      [],
    );

    const highIdx = html.indexOf('High Source');
    const midIdx = html.indexOf('Mid Source');
    const lowIdx = html.indexOf('Low Source');
    expect(highIdx).toBeLessThan(midIdx);
    expect(midIdx).toBeLessThan(lowIdx);
  });

  it('should render citation validation status with colored dots', () => {
    const cit = makeCitation({ validationStatus: ValidationStatus.Dead });
    const html = renderer.render(makeVerdict(), [cit], makeSession(), []);

    expect(html).toContain('class="status-dot"');
    expect(html).toContain('dead');
  });

  it('should render progress events grouped by phase', () => {
    const events = [
      makeEvent({
        phase: ProgressPhase.Synthesis,
        agent: 'synthesizer',
        message: 'Computing verdict',
      }),
      makeEvent({
        phase: ProgressPhase.Ingestion,
        agent: 'ingestion-agent',
        message: 'Parsing claim',
      }),
      makeEvent({
        phase: ProgressPhase.Fanout,
        agent: 'coverage-left',
        message: 'Searching sources',
      }),
    ];

    const html = renderer.render(makeVerdict(), [], makeSession(), events);

    // Phase badges should appear
    expect(html).toContain('ingestion');
    expect(html).toContain('fanout');
    expect(html).toContain('synthesis');

    // Ingestion should come before Fanout in the HTML
    const ingestionIdx = html.indexOf('ingestion');
    const fanoutIdx = html.indexOf('fanout');
    const synthesisIdx = html.indexOf('synthesis');
    expect(ingestionIdx).toBeLessThan(fanoutIdx);
    expect(fanoutIdx).toBeLessThan(synthesisIdx);
  });

  it('should include print button and print styles', () => {
    const html = renderer.render(makeVerdict(), [], makeSession(), []);

    expect(html).toContain('window.print()');
    expect(html).toContain('class="print-btn"');
    expect(html).toContain('@media print');
  });

  it('should hide tab bar and show both sections in print', () => {
    const html = renderer.render(makeVerdict(), [], makeSession(), []);

    expect(html).toContain('.tab-bar,.print-btn{display:none!important}');
    expect(html).toContain('.section{display:block!important}');
  });

  it('should escape HTML in user content', () => {
    const session = makeSession({ claim: '<script>alert("xss")</script>' });
    const html = renderer.render(makeVerdict(), [], session, []);

    expect(html).not.toContain('<script>alert("xss")</script>');
    expect(html).toContain('&lt;script&gt;');
  });

  it('should render without citations', () => {
    const html = renderer.render(makeVerdict(), [], makeSession(), []);

    expect(html).toContain('No citations available.');
  });

  it('should render without progress events', () => {
    const html = renderer.render(makeVerdict(), [], makeSession(), []);

    expect(html).toContain('Agent Progress Log');
  });

  it('should handle session without claim', () => {
    const session = makeSession({ claim: undefined });
    const html = renderer.render(makeVerdict(), [], session, []);

    expect(html).toContain('N/A');
  });

  it('should include footer with session ID and finalized date', () => {
    const html = renderer.render(makeVerdict(), [], makeSession(), []);

    expect(html).toContain('sess-1');
    expect(html).toContain('2026-01-15T10:00:00.000Z');
  });

  it('should have no external resource references', () => {
    const html = renderer.render(
      makeVerdict(),
      [makeCitation()],
      makeSession(),
      [makeEvent()],
    );

    // No external CSS
    expect(html).not.toMatch(/<link[^>]+stylesheet/);
    // No external JS
    expect(html).not.toMatch(/<script[^>]+src=/);
    // No external images
    expect(html).not.toMatch(/<img[^>]+src="http/);
  });
});
