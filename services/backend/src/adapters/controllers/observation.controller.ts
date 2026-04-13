import { Controller, Get, Param, ParseUUIDPipe } from '@nestjs/common';
import { GetObservationsUseCase } from '@app/use-cases';

@Controller('sessions')
export class ObservationController {
  constructor(
    private readonly getObservationsUseCase: GetObservationsUseCase,
  ) {}

  @Get(':sessionId/observations')
  async getObservations(@Param('sessionId', ParseUUIDPipe) sessionId: string) {
    return this.getObservationsUseCase.execute(sessionId);
  }
}
