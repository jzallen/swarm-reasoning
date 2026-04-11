import { Controller, Get, Param } from '@nestjs/common';
import { GetObservationsUseCase } from '../../application/use-cases';

@Controller('sessions')
export class ObservationController {
  constructor(
    private readonly getObservationsUseCase: GetObservationsUseCase,
  ) {}

  @Get(':sessionId/observations')
  async getObservations(@Param('sessionId') sessionId: string) {
    return this.getObservationsUseCase.execute(sessionId);
  }
}
