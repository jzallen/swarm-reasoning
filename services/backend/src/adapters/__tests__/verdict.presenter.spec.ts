import { VerdictPresenter } from '../presenters/verdict.presenter';
import { Verdict, Citation } from '../../domain/entities';
import { RatingLabel, ValidationStatus } from '../../domain/enums';

describe('VerdictPresenter', () => {
  it('should format verdict with citations per OpenAPI schema', () => {
    const presenter = new VerdictPresenter();
    const verdict = new Verdict({
      verdictId: 'v-1',
      runId: 'r-1',
      factualityScore: 0.75,
      ratingLabel: RatingLabel.MostlyTrue,
      narrative: 'The claim is mostly accurate.',
      signalCount: 12,
      finalizedAt: new Date('2024-01-15T10:00:00Z'),
    });

    const citations: Citation[] = [
      new Citation({
        citationId: 'c-1',
        verdictId: 'v-1',
        sourceUrl: 'https://example.com/article',
        sourceName: 'Example News',
        agent: 'coverage-center',
        observationCode: 'COV-CENTER-01',
        validationStatus: ValidationStatus.Live,
        convergenceCount: 3,
      }),
    ];

    const result = presenter.format(verdict, citations);

    expect(result.verdictId).toBe('v-1');
    expect(result.factualityScore).toBe(0.75);
    expect(result.ratingLabel).toBe('mostly-true');
    expect(result.narrative).toBe('The claim is mostly accurate.');
    expect(result.signalCount).toBe(12);
    expect(result.finalizedAt).toBe('2024-01-15T10:00:00.000Z');
    expect(result.citations).toHaveLength(1);
    expect(result.citations[0].sourceUrl).toBe('https://example.com/article');
    expect(result.citations[0].agent).toBe('coverage-center');
    expect(result.citations[0].validationStatus).toBe('live');
    expect(result.citations[0].convergenceCount).toBe(3);
    expect(result.coverageBreakdown).toHaveLength(3);
    expect(result.blindspotWarnings).toHaveLength(0);
  });

  it('should build coverage breakdown from observations', () => {
    const presenter = new VerdictPresenter();
    const verdict = new Verdict({
      verdictId: 'v-2',
      runId: 'r-2',
      factualityScore: 0.5,
      ratingLabel: RatingLabel.HalfTrue,
      narrative: 'Mixed evidence.',
      signalCount: 8,
      finalizedAt: new Date('2024-02-01T12:00:00Z'),
    });

    const observations: Record<string, unknown>[] = [
      {
        agent: 'coverage-left',
        code: 'COVERAGE_ARTICLE_COUNT',
        value: '3',
        status: 'F',
      },
      {
        agent: 'coverage-left',
        code: 'COVERAGE_FRAMING',
        value: 'SUPPORTIVE^Supportive^FCK',
        status: 'F',
      },
      {
        agent: 'coverage-left',
        code: 'COVERAGE_TOP_SOURCE',
        value: 'Left Daily',
        status: 'F',
      },
      {
        agent: 'coverage-left',
        code: 'COVERAGE_TOP_SOURCE_URL',
        value: 'https://leftdaily.example.com/article',
        status: 'F',
      },
      {
        agent: 'coverage-center',
        code: 'COVERAGE_ARTICLE_COUNT',
        value: '5',
        status: 'F',
      },
      {
        agent: 'coverage-center',
        code: 'COVERAGE_FRAMING',
        value: 'NEUTRAL^Neutral^FCK',
        status: 'F',
      },
      {
        agent: 'coverage-right',
        code: 'COVERAGE_ARTICLE_COUNT',
        value: '0',
        status: 'F',
      },
      {
        agent: 'coverage-right',
        code: 'COVERAGE_FRAMING',
        value: 'ABSENT^Not Covered^FCK',
        status: 'F',
      },
    ];

    const result = presenter.format(verdict, [], observations);

    expect(result.coverageBreakdown).toHaveLength(3);

    const left = result.coverageBreakdown.find((e) => e.spectrum === 'left');
    expect(left).toEqual({
      spectrum: 'left',
      articleCount: 3,
      framing: 'Supportive',
      topSource: 'Left Daily',
      topSourceUrl: 'https://leftdaily.example.com/article',
    });

    const center = result.coverageBreakdown.find(
      (e) => e.spectrum === 'center',
    );
    expect(center?.articleCount).toBe(5);
    expect(center?.framing).toBe('Neutral');

    const right = result.coverageBreakdown.find((e) => e.spectrum === 'right');
    expect(right?.articleCount).toBe(0);
    expect(right?.framing).toBe('Not Covered');
  });

  it('should build blindspot warnings from observations', () => {
    const presenter = new VerdictPresenter();
    const verdict = new Verdict({
      verdictId: 'v-3',
      runId: 'r-3',
      factualityScore: 0.4,
      ratingLabel: RatingLabel.MostlyFalse,
      narrative: 'Mostly unsupported.',
      signalCount: 6,
      finalizedAt: new Date('2024-02-15T09:00:00Z'),
    });

    const observations: Record<string, unknown>[] = [
      {
        agent: 'blindspot-detector',
        code: 'BLINDSPOT_SCORE',
        value: '0.85',
        status: 'F',
      },
      {
        agent: 'blindspot-detector',
        code: 'BLINDSPOT_DIRECTION',
        value: 'RIGHT^Right Absent^FCK',
        status: 'F',
      },
      {
        agent: 'blindspot-detector',
        code: 'CROSS_SPECTRUM_CORROBORATION',
        value: 'FALSE^Not Corroborated^FCK',
        status: 'F',
      },
    ];

    const result = presenter.format(verdict, [], observations);

    expect(result.blindspotWarnings).toHaveLength(1);
    expect(result.blindspotWarnings[0]).toEqual({
      blindspotScore: 0.85,
      direction: 'Right Absent',
      crossSpectrumCorroboration: false,
    });
  });

  it('should return empty blindspot warnings when direction is No Blindspot', () => {
    const presenter = new VerdictPresenter();
    const verdict = new Verdict({
      verdictId: 'v-4',
      runId: 'r-4',
      factualityScore: 0.9,
      ratingLabel: RatingLabel.True,
      narrative: 'Confirmed.',
      signalCount: 15,
      finalizedAt: new Date('2024-03-01T08:00:00Z'),
    });

    const observations: Record<string, unknown>[] = [
      {
        agent: 'blindspot-detector',
        code: 'BLINDSPOT_SCORE',
        value: '0.1',
        status: 'F',
      },
      {
        agent: 'blindspot-detector',
        code: 'BLINDSPOT_DIRECTION',
        value: 'NONE^No Blindspot^FCK',
        status: 'F',
      },
      {
        agent: 'blindspot-detector',
        code: 'CROSS_SPECTRUM_CORROBORATION',
        value: 'TRUE^Corroborated^FCK',
        status: 'F',
      },
    ];

    const result = presenter.format(verdict, [], observations);
    expect(result.blindspotWarnings).toHaveLength(0);
  });
});
