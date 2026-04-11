import { Module } from '@nestjs/common';
import { Cron } from '@nestjs/schedule';
import { Injectable } from '@nestjs/common';
import { CleanupExpiredSessionsUseCase } from '../../application/use-cases';
import { InfrastructureModule } from './infrastructure.module';

@Injectable()
export class CleanupScheduler {
  constructor(
    private readonly cleanupUseCase: CleanupExpiredSessionsUseCase,
  ) {}

  @Cron('0 * * * *') // Every hour
  async handleCleanup() {
    await this.cleanupUseCase.execute();
  }
}

@Module({
  imports: [InfrastructureModule],
  providers: [CleanupExpiredSessionsUseCase, CleanupScheduler],
})
export class CleanupModule {}
