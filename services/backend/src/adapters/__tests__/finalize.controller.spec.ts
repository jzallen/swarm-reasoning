import { FinalizeController } from '../controllers/finalize.controller';
import { Verdict, Citation } from '@domain/entities';
import { RatingLabel, ValidationStatus } from '@domain/enums';

describe('FinalizeController', () => {
  const createMockFinalizeUseCase = () => ({
    execute: jest.fn().mockResolvedValue(undefined),
  });

  const createController = () => {
    const useCase = createMockFinalizeUseCase();
    // eslint-disable-next-line @typescript-eslint/no-unsafe-argument
    const controller = new FinalizeController(useCase as any);
    return { controller, useCase };
  };

  it('should create verdict and citations from pipeline result', async () => {
    const { controller, useCase } = createController();

    await controller.finalizeRun('run-1', {
      sessionId: 'session-1',
      verdict: 'true',
      confidence: 0.92,
      narrative: 'The claim is verified as true based on multiple sources.',
      citations: [
        {
          sourceUrl: 'https://example.com/source1',
          sourceName: 'Example News',
          agent: 'evidence',
          observationCode: 'CLAIMREVIEW_MATCH',
          validationStatus: 'live',
          convergenceCount: 3,
        },
      ],
    });

    expect(useCase.execute).toHaveBeenCalledTimes(1);

    const [sessionId, verdict, citations, runId] = useCase.execute.mock
      .calls[0] as [string, Verdict, Citation[], string];

    expect(sessionId).toBe('session-1');
    expect(runId).toBe('run-1');
    expect(verdict.runId).toBe('run-1');
    expect(verdict.factualityScore).toBe(0.92);
    expect(verdict.ratingLabel).toBe(RatingLabel.True);
    expect(verdict.narrative).toBe(
      'The claim is verified as true based on multiple sources.',
    );
    expect(verdict.signalCount).toBe(1);
    expect(verdict.verdictId).toBeDefined();
    expect(verdict.finalizedAt).toBeInstanceOf(Date);

    expect(citations).toHaveLength(1);
    expect(citations[0].sourceUrl).toBe('https://example.com/source1');
    expect(citations[0].sourceName).toBe('Example News');
    expect(citations[0].agent).toBe('evidence');
    expect(citations[0].observationCode).toBe('CLAIMREVIEW_MATCH');
    expect(citations[0].validationStatus).toBe(ValidationStatus.Live);
    expect(citations[0].convergenceCount).toBe(3);
  });

  it('should use explicit ratingLabel when provided', async () => {
    const { controller, useCase } = createController();

    await controller.finalizeRun('run-2', {
      sessionId: 'session-2',
      verdict: 'false',
      confidence: 0.85,
      narrative: 'The claim is false.',
      ratingLabel: 'mostly-false',
    });

    const [, verdict] = useCase.execute.mock.calls[0] as [
      string,
      Verdict,
      Citation[],
      string,
    ];
    expect(verdict.ratingLabel).toBe(RatingLabel.MostlyFalse);
  });

  it('should map confidence to rating label when no explicit label', async () => {
    const { controller, useCase } = createController();

    const cases = [
      { confidence: 0.95, expected: RatingLabel.True },
      { confidence: 0.8, expected: RatingLabel.MostlyTrue },
      { confidence: 0.55, expected: RatingLabel.HalfTrue },
      { confidence: 0.35, expected: RatingLabel.MostlyFalse },
      { confidence: 0.15, expected: RatingLabel.False },
      { confidence: 0.05, expected: RatingLabel.PantsOnFire },
    ];

    for (const { confidence, expected } of cases) {
      await controller.finalizeRun('run-x', {
        sessionId: 'session-x',
        verdict: 'test',
        confidence,
        narrative: 'Test narrative.',
      });

      const lastCall = useCase.execute.mock.calls[
        useCase.execute.mock.calls.length - 1
      ] as [string, Verdict, Citation[], string];
      expect(lastCall[1].ratingLabel).toBe(expected);
    }
  });

  it('should handle empty citations array', async () => {
    const { controller, useCase } = createController();

    await controller.finalizeRun('run-3', {
      sessionId: 'session-3',
      verdict: 'true',
      confidence: 0.9,
      narrative: 'Verified.',
      citations: [],
    });

    const [, verdict, citations] = useCase.execute.mock.calls[0] as [
      string,
      Verdict,
      Citation[],
      string,
    ];
    expect(verdict.signalCount).toBe(0);
    expect(citations).toHaveLength(0);
  });

  it('should handle missing citations (undefined)', async () => {
    const { controller, useCase } = createController();

    await controller.finalizeRun('run-4', {
      sessionId: 'session-4',
      verdict: 'true',
      confidence: 0.9,
      narrative: 'Verified.',
    });

    const [, verdict, citations] = useCase.execute.mock.calls[0] as [
      string,
      Verdict,
      Citation[],
      string,
    ];
    expect(verdict.signalCount).toBe(0);
    expect(citations).toHaveLength(0);
  });

  it('should default validationStatus to not-validated', async () => {
    const { controller, useCase } = createController();

    await controller.finalizeRun('run-5', {
      sessionId: 'session-5',
      verdict: 'true',
      confidence: 0.9,
      narrative: 'Verified.',
      citations: [
        {
          sourceUrl: 'https://example.com',
          sourceName: 'Example',
          agent: 'evidence',
          observationCode: 'DOMAIN_SOURCE',
        },
      ],
    });

    const [, , citations] = useCase.execute.mock.calls[0] as [
      string,
      Verdict,
      Citation[],
      string,
    ];
    expect(citations[0].validationStatus).toBe(ValidationStatus.NotValidated);
    expect(citations[0].convergenceCount).toBe(0);
  });
});
