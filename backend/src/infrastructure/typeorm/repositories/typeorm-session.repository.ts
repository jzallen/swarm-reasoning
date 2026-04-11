import { Injectable } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { LessThan, Repository } from 'typeorm';
import { SessionRepository } from '../../../application/interfaces';
import { Session } from '../../../domain/entities';
import { SessionStatus } from '../../../domain/enums';
import { SessionOrmEntity } from '../entities';

@Injectable()
export class TypeOrmSessionRepository implements SessionRepository {
  constructor(
    @InjectRepository(SessionOrmEntity)
    private readonly repo: Repository<SessionOrmEntity>,
  ) {}

  async save(session: Session): Promise<Session> {
    const entity = this.toOrm(session);
    await this.repo.save(entity);
    return session;
  }

  async findById(sessionId: string): Promise<Session | null> {
    const entity = await this.repo.findOne({ where: { sessionId } });
    return entity ? this.toDomain(entity) : null;
  }

  async findExpiredSessions(): Promise<Session[]> {
    const entities = await this.repo.find({
      where: {
        status: SessionStatus.Frozen,
        expiresAt: LessThan(new Date()),
      },
    });
    return entities.map((e) => this.toDomain(e));
  }

  async delete(sessionId: string): Promise<void> {
    await this.repo.delete({ sessionId });
  }

  private toOrm(session: Session): SessionOrmEntity {
    const entity = new SessionOrmEntity();
    entity.sessionId = session.sessionId;
    entity.status = session.status;
    entity.claim = session.claim ?? null;
    entity.createdAt = session.createdAt;
    entity.frozenAt = session.frozenAt ?? null;
    entity.expiresAt = session.expiresAt ?? null;
    entity.snapshotUrl = session.snapshotUrl ?? null;
    return entity;
  }

  private toDomain(entity: SessionOrmEntity): Session {
    return new Session({
      sessionId: entity.sessionId,
      status: entity.status as SessionStatus,
      claim: entity.claim ?? undefined,
      createdAt: entity.createdAt,
      frozenAt: entity.frozenAt ?? undefined,
      expiresAt: entity.expiresAt ?? undefined,
      snapshotUrl: entity.snapshotUrl ?? undefined,
    });
  }
}
