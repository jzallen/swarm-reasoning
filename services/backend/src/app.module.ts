import { Module } from '@nestjs/common';
import { ConfigModule, ConfigService } from '@nestjs/config';
import { TypeOrmModule } from '@nestjs/typeorm';
import { ScheduleModule } from '@nestjs/schedule';
import {
  SessionOrmEntity,
  RunOrmEntity,
  VerdictOrmEntity,
  CitationOrmEntity,
} from './infrastructure/typeorm/entities';
import { SessionModule } from './infrastructure/modules/session.module';
import { VerdictModule } from './infrastructure/modules/verdict.module';
import { StreamModule } from './infrastructure/modules/stream.module';
import { HealthModule } from './infrastructure/modules/health.module';
import { CleanupModule } from './infrastructure/modules/cleanup.module';

@Module({
  imports: [
    ConfigModule.forRoot({ isGlobal: true }),
    TypeOrmModule.forRootAsync({
      imports: [ConfigModule],
      inject: [ConfigService],
      useFactory: (config: ConfigService) => ({
        type: 'postgres' as const,
        url: config.get<string>(
          'DATABASE_URL',
          'postgresql://postgres:postgres@localhost:5432/swarm',
        ),
        entities: [
          SessionOrmEntity,
          RunOrmEntity,
          VerdictOrmEntity,
          CitationOrmEntity,
        ],
        synchronize: false,
        logging: config.get<string>('NODE_ENV') === 'development',
      }),
    }),
    ScheduleModule.forRoot(),
    SessionModule,
    VerdictModule,
    StreamModule,
    HealthModule,
    CleanupModule,
  ],
})
export class AppModule {}
