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
    expect(result.citations[0].sourceUrl).toBe(
      'https://example.com/article',
    );
    expect(result.citations[0].agent).toBe('coverage-center');
    expect(result.citations[0].validationStatus).toBe('live');
    expect(result.citations[0].convergenceCount).toBe(3);
  });
});
