import { Injectable } from '@nestjs/common';
import { Session } from '../../domain/entities';

export interface SessionResponse {
  sessionId: string;
  status: string;
  claim: string | null;
  createdAt: string;
  frozenAt: string | null;
  expiresAt: string | null;
  snapshotUrl: string | null;
}

@Injectable()
export class SessionPresenter {
  format(session: Session): SessionResponse {
    return {
      sessionId: session.sessionId,
      status: session.status,
      claim: session.claim ?? null,
      createdAt: session.createdAt.toISOString(),
      frozenAt: session.frozenAt?.toISOString() ?? null,
      expiresAt: session.expiresAt?.toISOString() ?? null,
      snapshotUrl: session.snapshotUrl ?? null,
    };
  }
}
