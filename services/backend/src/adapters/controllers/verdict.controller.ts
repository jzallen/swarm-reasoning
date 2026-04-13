import { Controller, Get, Param, ParseUUIDPipe } from '@nestjs/common';
import { GetVerdictUseCase } from '@app/use-cases';
import { VerdictPresenter } from '../presenters/verdict.presenter';

@Controller('sessions')
export class VerdictController {
  constructor(
    private readonly getVerdictUseCase: GetVerdictUseCase,
    private readonly verdictPresenter: VerdictPresenter,
  ) {}

  @Get(':sessionId/verdict')
  async getVerdict(@Param('sessionId', ParseUUIDPipe) sessionId: string) {
    const { verdict, citations, observations } =
      await this.getVerdictUseCase.execute(sessionId);
    return this.verdictPresenter.format(verdict, citations, observations);
  }
}
