import { Module } from '@nestjs/common';
import { SessionController } from '../../adapters/controllers/session.controller';
import { ClaimController } from '../../adapters/controllers/claim.controller';
import { SessionPresenter } from '../../adapters/presenters/session.presenter';
import {
  CreateSessionUseCase,
  GetSessionUseCase,
  SubmitClaimUseCase,
} from '../../application/use-cases';
import { InfrastructureModule } from './infrastructure.module';

@Module({
  imports: [InfrastructureModule],
  controllers: [SessionController, ClaimController],
  providers: [CreateSessionUseCase, GetSessionUseCase, SubmitClaimUseCase, SessionPresenter],
})
export class SessionModule {}
