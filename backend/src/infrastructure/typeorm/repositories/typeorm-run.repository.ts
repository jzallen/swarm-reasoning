import { Injectable } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository } from 'typeorm';
import { RunRepository } from '../../../application/interfaces';
import { Run } from '../../../domain/entities';
import { RunStatus } from '../../../domain/enums';
import { RunOrmEntity } from '../entities';

@Injectable()
export class TypeOrmRunRepository implements RunRepository {
  constructor(
    @InjectRepository(RunOrmEntity)
    private readonly repo: Repository<RunOrmEntity>,
  ) {}

  async save(run: Run): Promise<Run> {
    const entity = this.toOrm(run);
    await this.repo.save(entity);
    return run;
  }

  async findById(runId: string): Promise<Run | null> {
    const entity = await this.repo.findOne({ where: { runId } });
    return entity ? this.toDomain(entity) : null;
  }

  async findBySessionId(sessionId: string): Promise<Run | null> {
    const entity = await this.repo.findOne({
      where: { sessionId },
      order: { createdAt: 'DESC' },
    });
    return entity ? this.toDomain(entity) : null;
  }

  private toOrm(run: Run): RunOrmEntity {
    const entity = new RunOrmEntity();
    entity.runId = run.runId;
    entity.sessionId = run.sessionId;
    entity.status = run.status;
    entity.phase = run.phase ?? null;
    entity.createdAt = run.createdAt;
    entity.completedAt = run.completedAt ?? null;
    return entity;
  }

  private toDomain(entity: RunOrmEntity): Run {
    return new Run({
      runId: entity.runId,
      sessionId: entity.sessionId,
      status: entity.status as RunStatus,
      phase: entity.phase ?? undefined,
      createdAt: entity.createdAt,
      completedAt: entity.completedAt ?? undefined,
    });
  }
}
