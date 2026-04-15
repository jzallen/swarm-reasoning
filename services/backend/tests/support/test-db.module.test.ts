import { Test } from '@nestjs/testing';
import { DataSource } from 'typeorm';
import { TestDbModule } from './test-db.module';
import { SessionOrmEntity, RunOrmEntity } from '@infra/typeorm/entities';

describe('TestDbModule', () => {
  let dataSource: DataSource;

  afterEach(async () => {
    if (dataSource?.isInitialized) {
      await dataSource.destroy();
    }
  });

  it('should initialize with all entity tables', async () => {
    const module = await Test.createTestingModule({
      imports: [await TestDbModule.forRoot()],
    }).compile();

    dataSource = module.get(DataSource);

    expect(dataSource.isInitialized).toBe(true);

    const tableNames = dataSource.entityMetadatas.map((m) => m.tableName);
    expect(tableNames).toContain('sessions');
    expect(tableNames).toContain('runs');
    expect(tableNames).toContain('verdicts');
    expect(tableNames).toContain('citations');

    await module.close();
  });

  it('should provide working TypeORM repositories', async () => {
    const module = await Test.createTestingModule({
      imports: [await TestDbModule.forRoot()],
    }).compile();

    dataSource = module.get(DataSource);
    const sessionRepo = dataSource.getRepository(SessionOrmEntity);
    const runRepo = dataSource.getRepository(RunOrmEntity);

    // Insert a session
    const session = sessionRepo.create({
      sessionId: '00000000-0000-0000-0000-000000000001',
      status: 'active',
      claim: null,
    });
    await sessionRepo.save(session);

    // Insert a run linked to the session
    const run = runRepo.create({
      runId: '00000000-0000-0000-0000-000000000002',
      sessionId: session.sessionId,
      status: 'pending',
      phase: null,
    });
    await runRepo.save(run);

    // Verify data persists in-memory
    const found = await sessionRepo.findOneBy({
      sessionId: session.sessionId,
    });
    expect(found).not.toBeNull();
    expect(found!.status).toBe('active');

    const foundRun = await runRepo.findOneBy({ runId: run.runId });
    expect(foundRun).not.toBeNull();
    expect(foundRun!.sessionId).toBe(session.sessionId);

    await module.close();
  });

  it('should enforce foreign key constraints', async () => {
    const module = await Test.createTestingModule({
      imports: [await TestDbModule.forRoot()],
    }).compile();

    dataSource = module.get(DataSource);
    const runRepo = dataSource.getRepository(RunOrmEntity);

    // Inserting a run with a non-existent sessionId should fail
    const orphanRun = runRepo.create({
      runId: '00000000-0000-0000-0000-000000000099',
      sessionId: '00000000-0000-0000-0000-ffffffffffffffff',
      status: 'pending',
      phase: null,
    });

    await expect(runRepo.save(orphanRun)).rejects.toThrow();

    await module.close();
  });
});
