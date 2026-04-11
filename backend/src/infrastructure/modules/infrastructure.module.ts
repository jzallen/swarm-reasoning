import { Module } from '@nestjs/common';
import { ConfigModule, ConfigService } from '@nestjs/config';
import { TypeOrmModule } from '@nestjs/typeorm';
import {
  SessionOrmEntity,
  RunOrmEntity,
  VerdictOrmEntity,
  CitationOrmEntity,
} from '../typeorm/entities';
import { TypeOrmSessionRepository } from '../typeorm/repositories/typeorm-session.repository';
import { TypeOrmRunRepository } from '../typeorm/repositories/typeorm-run.repository';
import { TypeOrmVerdictRepository } from '../typeorm/repositories/typeorm-verdict.repository';
import { TypeOrmCitationRepository } from '../typeorm/repositories/typeorm-citation.repository';
import { RedisStreamAdapter } from '../redis/redis-stream.adapter';
import { TemporalClientAdapter } from '../temporal/temporal-client.adapter';
import { LocalSnapshotStore } from '../snapshot/local-snapshot.store';
import { S3SnapshotStore } from '../snapshot/s3-snapshot.store';
import { StaticHtmlRenderer } from '../renderers/static-html.renderer';
import {
  SESSION_REPOSITORY,
  RUN_REPOSITORY,
  VERDICT_REPOSITORY,
  CITATION_REPOSITORY,
  STREAM_READER,
  TEMPORAL_CLIENT,
  SNAPSHOT_STORE,
} from '../../application/interfaces';

const sessionRepoProvider = {
  provide: SESSION_REPOSITORY,
  useClass: TypeOrmSessionRepository,
};

const runRepoProvider = {
  provide: RUN_REPOSITORY,
  useClass: TypeOrmRunRepository,
};

const verdictRepoProvider = {
  provide: VERDICT_REPOSITORY,
  useClass: TypeOrmVerdictRepository,
};

const citationRepoProvider = {
  provide: CITATION_REPOSITORY,
  useClass: TypeOrmCitationRepository,
};

const streamReaderProvider = {
  provide: STREAM_READER,
  useClass: RedisStreamAdapter,
};

const temporalClientProvider = {
  provide: TEMPORAL_CLIENT,
  useClass: TemporalClientAdapter,
};

const snapshotStoreProvider = {
  provide: SNAPSHOT_STORE,
  useFactory: (configService: ConfigService) => {
    const storeType = configService.get<string>('SNAPSHOT_STORE', 'local');
    if (storeType === 's3') {
      return new S3SnapshotStore(configService);
    }
    return new LocalSnapshotStore();
  },
  inject: [ConfigService],
};

@Module({
  imports: [
    ConfigModule,
    TypeOrmModule.forFeature([
      SessionOrmEntity,
      RunOrmEntity,
      VerdictOrmEntity,
      CitationOrmEntity,
    ]),
  ],
  providers: [
    sessionRepoProvider,
    runRepoProvider,
    verdictRepoProvider,
    citationRepoProvider,
    streamReaderProvider,
    temporalClientProvider,
    snapshotStoreProvider,
    StaticHtmlRenderer,
  ],
  exports: [
    sessionRepoProvider,
    runRepoProvider,
    verdictRepoProvider,
    citationRepoProvider,
    streamReaderProvider,
    temporalClientProvider,
    snapshotStoreProvider,
    StaticHtmlRenderer,
  ],
})
export class InfrastructureModule {}
