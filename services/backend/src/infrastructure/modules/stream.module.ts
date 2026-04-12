import { Module } from '@nestjs/common';
import { EventController } from '../../adapters/controllers/event.controller';
import { ObservationController } from '../../adapters/controllers/observation.controller';
import {
  StreamProgressUseCase,
  GetObservationsUseCase,
} from '../../application/use-cases';
import { InfrastructureModule } from './infrastructure.module';

@Module({
  imports: [InfrastructureModule],
  controllers: [EventController, ObservationController],
  providers: [StreamProgressUseCase, GetObservationsUseCase],
})
export class StreamModule {}
