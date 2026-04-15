import { DynamicModule, Module, OnModuleDestroy } from '@nestjs/common';
import { TypeOrmModule } from '@nestjs/typeorm';
import { DataSource } from 'typeorm';
import { newDb, IMemoryDb } from 'pg-mem';
import {
  SessionOrmEntity,
  RunOrmEntity,
  VerdictOrmEntity,
  CitationOrmEntity,
} from '@infra/typeorm/entities';

const entities = [
  SessionOrmEntity,
  RunOrmEntity,
  VerdictOrmEntity,
  CitationOrmEntity,
];

/**
 * Creates an in-memory PostgreSQL DataSource via pg-mem for integration tests.
 * Returns the DataSource and the underlying pg-mem database instance so tests
 * can create backups/restores for isolation between test cases.
 */
export async function createTestDataSource(): Promise<{
  dataSource: DataSource;
  db: IMemoryDb;
}> {
  const db = newDb({ autoCreateForeignKeyIndices: true });

  db.public.registerFunction({
    name: 'current_database',
    implementation: () => 'test',
  });
  db.public.registerFunction({
    name: 'version',
    implementation: () => 'PostgreSQL 16.0 (pg-mem)',
  });

  const dataSource: DataSource = (await db.adapters.createTypeormDataSource({
    type: 'postgres',
    entities,
    synchronize: true,
  })) as DataSource;

  await dataSource.initialize();

  return { dataSource, db };
}

@Module({})
export class TestDbModule implements OnModuleDestroy {
  constructor(private readonly dataSource: DataSource) {}

  async onModuleDestroy(): Promise<void> {
    if (this.dataSource?.isInitialized) {
      await this.dataSource.destroy();
    }
  }

  /**
   * Provides a fully-initialized in-memory TypeORM setup for integration tests.
   *
   * Usage:
   * ```ts
   * const module = await Test.createTestingModule({
   *   imports: [await TestDbModule.forRoot()],
   * }).compile();
   * ```
   */
  static async forRoot(): Promise<DynamicModule> {
    const { dataSource } = await createTestDataSource();

    return {
      module: TestDbModule,
      imports: [
        TypeOrmModule.forRootAsync({
          useFactory: () => ({}),
          dataSourceFactory: () => Promise.resolve(dataSource),
        }),
        TypeOrmModule.forFeature(entities),
      ],
      providers: [{ provide: DataSource, useValue: dataSource }],
      exports: [TypeOrmModule, DataSource],
      global: true,
    };
  }
}
