import {
  Controller,
  Post,
  Param,
  Body,
  HttpCode,
  HttpStatus,
} from '@nestjs/common';
import { SubmitClaimUseCase } from '../../application/use-cases';
import { SubmitClaimDto } from '../dto/submit-claim.dto';

@Controller('sessions')
export class ClaimController {
  constructor(private readonly submitClaimUseCase: SubmitClaimUseCase) {}

  @Post(':sessionId/claims')
  @HttpCode(HttpStatus.ACCEPTED)
  async submitClaim(
    @Param('sessionId') sessionId: string,
    @Body() dto: SubmitClaimDto,
  ) {
    const session = await this.submitClaimUseCase.execute(sessionId, {
      claimText: dto.claimText,
      sourceUrl: dto.sourceUrl,
      sourceDate: dto.sourceDate,
    });
    return {
      sessionId: session.sessionId,
      status: session.status,
      claim: session.claim ?? null,
      createdAt: session.createdAt.toISOString(),
      frozenAt: session.frozenAt?.toISOString() ?? null,
      expiresAt: session.expiresAt?.toISOString() ?? null,
      snapshotUrl: session.snapshotUrl ?? null,
    };
  }
}
