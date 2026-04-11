import { Module } from '@nestjs/common';
import { HealthController } from '../../adapters/controllers/health.controller';

@Module({
  controllers: [HealthController],
})
export class HealthModule {}
