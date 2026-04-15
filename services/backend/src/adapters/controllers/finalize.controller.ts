import {
  Controller,
  Post,
  Param,
  Body,
  HttpCode,
  HttpStatus,
  Logger,
} from '@nestjs/common';
import { v4 as uuidv4 } from 'uuid';
import { FinalizeSessionUseCase } from '@app/use-cases/finalize-session.use-case.js';
import { Verdict } from '@domain/entities/verdict.entity.js';
import { Citation } from '@domain/entities/citation.entity.js';
import { RatingLabel, ValidationStatus } from '@domain/enums/index.js';
import { FinalizeRunDto, CitationDto } from '../dto/finalize-run.dto.js';

/**
 * Internal endpoint for the persist_verdict Temporal activity (ADR-0023 §M7).
 *
 * The simplified workflow calls this endpoint to persist the pipeline result
 * as a Verdict + Citations in PostgreSQL and trigger session finalization
 * (snapshot rendering, session freeze).
 */
@Controller('internal')
export class FinalizeController {
  private readonly logger = new Logger(FinalizeController.name);

  constructor(
    private readonly finalizeSessionUseCase: FinalizeSessionUseCase,
  ) {}

  @Post('runs/:runId/finalize')
  @HttpCode(HttpStatus.NO_CONTENT)
  async finalizeRun(
    @Param('runId') runId: string,
    @Body() dto: FinalizeRunDto,
  ): Promise<void> {
    this.logger.log(`Finalizing run ${runId} for session ${dto.sessionId}`);

    const verdictId = uuidv4();
    const ratingLabel = this.mapRatingLabel(
      dto.verdict,
      dto.confidence,
      dto.ratingLabel,
    );

    const verdict = new Verdict({
      verdictId,
      runId,
      factualityScore: dto.confidence,
      ratingLabel,
      narrative: dto.narrative,
      signalCount: dto.citations?.length ?? 0,
      finalizedAt: new Date(),
    });

    const citations = (dto.citations ?? []).map(
      (c: CitationDto) =>
        new Citation({
          citationId: uuidv4(),
          verdictId,
          sourceUrl: c.sourceUrl,
          sourceName: c.sourceName,
          agent: c.agent,
          observationCode: c.observationCode,
          validationStatus: this.mapValidationStatus(c.validationStatus),
          convergenceCount: c.convergenceCount ?? 0,
        }),
    );

    await this.finalizeSessionUseCase.execute(
      dto.sessionId,
      verdict,
      citations,
      runId,
    );

    this.logger.log(
      `Run ${runId} finalized: verdict=${ratingLabel}, citations=${citations.length}`,
    );
  }

  private mapRatingLabel(
    _verdict: string,
    confidence: number,
    explicitLabel?: string,
  ): RatingLabel {
    if (explicitLabel) {
      const values: string[] = Object.values(RatingLabel);
      if (values.includes(explicitLabel)) return explicitLabel as RatingLabel;
    }

    // Map confidence score to rating label (PolitiFact scale)
    if (confidence >= 0.9) return RatingLabel.True;
    if (confidence >= 0.75) return RatingLabel.MostlyTrue;
    if (confidence >= 0.5) return RatingLabel.HalfTrue;
    if (confidence >= 0.3) return RatingLabel.MostlyFalse;
    if (confidence >= 0.1) return RatingLabel.False;
    return RatingLabel.PantsOnFire;
  }

  private mapValidationStatus(status?: string): ValidationStatus {
    if (!status) return ValidationStatus.NotValidated;
    const values: string[] = Object.values(ValidationStatus);
    if (values.includes(status)) return status as ValidationStatus;
    return ValidationStatus.NotValidated;
  }
}
