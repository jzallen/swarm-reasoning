import { Session } from '@domain/entities';

export interface SessionRepository {
  save(session: Session): Promise<Session>;
  findById(sessionId: string): Promise<Session | null>;
  findExpiredSessions(): Promise<Session[]>;
  delete(sessionId: string): Promise<void>;
}

export const SESSION_REPOSITORY = Symbol('SessionRepository');
