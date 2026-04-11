import { Injectable } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository } from 'typeorm';
import { VerdictRepository } from '../../../application/interfaces';
import { Verdict } from '../../../domain/entities';
import { RatingLabel } from '../../../domain/enums';
import { VerdictOrmEntity } from '../entities';

@Injectable()
export class TypeOrmVerdictRepository implements VerdictRepository {
  constructor(
    @InjectRepository(VerdictOrmEntity)
    private readonly repo: Repository<VerdictOrmEntity>,
  ) {}

  async save(verdict: Verdict): Promise<Verdict> {
    const entity = this.toOrm(verdict);
    await this.repo.save(entity);
    return verdict;
  }

  async findByRunId(runId: string): Promise<Verdict | null> {
    const entity = await this.repo.findOne({ where: { runId } });
    return entity ? this.toDomain(entity) : null;
  }

  private toOrm(verdict: Verdict): VerdictOrmEntity {
    const entity = new VerdictOrmEntity();
    entity.verdictId = verdict.verdictId;
    entity.runId = verdict.runId;
    entity.factualityScore = verdict.factualityScore;
    entity.ratingLabel = verdict.ratingLabel;
    entity.narrative = verdict.narrative;
    entity.signalCount = verdict.signalCount;
    entity.finalizedAt = verdict.finalizedAt;
    return entity;
  }

  private toDomain(entity: VerdictOrmEntity): Verdict {
    return new Verdict({
      verdictId: entity.verdictId,
      runId: entity.runId,
      factualityScore: Number(entity.factualityScore),
      ratingLabel: entity.ratingLabel as RatingLabel,
      narrative: entity.narrative,
      signalCount: entity.signalCount,
      finalizedAt: entity.finalizedAt,
    });
  }
}
