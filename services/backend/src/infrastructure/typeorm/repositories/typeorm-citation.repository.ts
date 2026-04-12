import { Injectable } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository } from 'typeorm';
import { CitationRepository } from '../../../application/interfaces';
import { Citation } from '../../../domain/entities';
import { ValidationStatus } from '../../../domain/enums';
import { CitationOrmEntity } from '../entities';

@Injectable()
export class TypeOrmCitationRepository implements CitationRepository {
  constructor(
    @InjectRepository(CitationOrmEntity)
    private readonly repo: Repository<CitationOrmEntity>,
  ) {}

  async saveMany(citations: Citation[]): Promise<Citation[]> {
    const entities = citations.map((c) => this.toOrm(c));
    await this.repo.save(entities);
    return citations;
  }

  async findByVerdictId(verdictId: string): Promise<Citation[]> {
    const entities = await this.repo.find({ where: { verdictId } });
    return entities.map((e) => this.toDomain(e));
  }

  private toOrm(citation: Citation): CitationOrmEntity {
    const entity = new CitationOrmEntity();
    entity.citationId = citation.citationId;
    entity.verdictId = citation.verdictId;
    entity.sourceUrl = citation.sourceUrl;
    entity.sourceName = citation.sourceName;
    entity.agent = citation.agent;
    entity.observationCode = citation.observationCode;
    entity.validationStatus = citation.validationStatus;
    entity.convergenceCount = citation.convergenceCount;
    return entity;
  }

  private toDomain(entity: CitationOrmEntity): Citation {
    return new Citation({
      citationId: entity.citationId,
      verdictId: entity.verdictId,
      sourceUrl: entity.sourceUrl,
      sourceName: entity.sourceName,
      agent: entity.agent,
      observationCode: entity.observationCode,
      validationStatus: entity.validationStatus as ValidationStatus,
      convergenceCount: entity.convergenceCount,
    });
  }
}
