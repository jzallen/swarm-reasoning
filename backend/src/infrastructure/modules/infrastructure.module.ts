import { Module } from '@nestjs/common';
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
  useClass: LocalSnapshotStore,
};

@Module({
  imports: [
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
  ],
  exports: [
    sessionRepoProvider,
    runRepoProvider,
    verdictRepoProvider,
    citationRepoProvider,
    streamReaderProvider,
    temporalClientProvider,
    snapshotStoreProvider,
  ],
})
export class InfrastructureModule {}
