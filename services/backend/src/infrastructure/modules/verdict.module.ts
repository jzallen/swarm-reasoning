import { Module } from '@nestjs/common';
import { VerdictController } from '@adapters/controllers/verdict.controller';
import { VerdictPresenter } from '@adapters/presenters/verdict.presenter';
import {
  GetVerdictUseCase,
  FinalizeSessionUseCase,
} from '@app/use-cases';
import { InfrastructureModule } from './infrastructure.module';

@Module({
  imports: [InfrastructureModule],
  controllers: [VerdictController],
  providers: [GetVerdictUseCase, FinalizeSessionUseCase, VerdictPresenter],
  exports: [FinalizeSessionUseCase],
})
export class VerdictModule {}
