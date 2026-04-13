import {
  Controller,
  Post,
  Param,
  ParseUUIDPipe,
  Body,
  HttpCode,
  HttpStatus,
} from '@nestjs/common';
import { SubmitClaimUseCase } from '../../application/use-cases';
import { SubmitClaimDto } from '../dto/submit-claim.dto';
import { SessionPresenter } from '../presenters/session.presenter';

@Controller('sessions')
export class ClaimController {
  constructor(
    private readonly submitClaimUseCase: SubmitClaimUseCase,
    private readonly sessionPresenter: SessionPresenter,
  ) {}

  @Post(':sessionId/claims')
  @HttpCode(HttpStatus.ACCEPTED)
  async submitClaim(
    @Param('sessionId', ParseUUIDPipe) sessionId: string,
    @Body() dto: SubmitClaimDto,
  ) {
    const session = await this.submitClaimUseCase.execute(sessionId, {
      claimText: dto.claimText,
      sourceUrl: dto.sourceUrl,
      sourceDate: dto.sourceDate,
    });
    return this.sessionPresenter.format(session);
  }
}
