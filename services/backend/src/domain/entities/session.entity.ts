import { SessionStatus } from '../enums';

const VALID_TRANSITIONS: Record<SessionStatus, SessionStatus[]> = {
  [SessionStatus.Active]: [SessionStatus.Frozen],
  [SessionStatus.Frozen]: [SessionStatus.Expired],
  [SessionStatus.Expired]: [],
};

export class Session {
  readonly sessionId: string;
  status: SessionStatus;
  claim?: string;
  readonly createdAt: Date;
  frozenAt?: Date;
  expiresAt?: Date;
  snapshotUrl?: string;

  constructor(params: {
    sessionId: string;
    status: SessionStatus;
    claim?: string;
    createdAt: Date;
    frozenAt?: Date;
    expiresAt?: Date;
    snapshotUrl?: string;
  }) {
    this.sessionId = params.sessionId;
    this.status = params.status;
    this.claim = params.claim;
    this.createdAt = params.createdAt;
    this.frozenAt = params.frozenAt;
    this.expiresAt = params.expiresAt;
    this.snapshotUrl = params.snapshotUrl;
  }

  transitionTo(newStatus: SessionStatus): void {
    const allowed = VALID_TRANSITIONS[this.status];
    if (!allowed.includes(newStatus)) {
      throw new Error(
        `Invalid session transition: ${this.status} -> ${newStatus}`,
      );
    }
    this.status = newStatus;
    if (newStatus === SessionStatus.Frozen) {
      this.frozenAt = new Date();
      const TTL_DAYS = 3;
      this.expiresAt = new Date(
        this.frozenAt.getTime() + TTL_DAYS * 24 * 60 * 60 * 1000,
      );
    }
  }

  isExpired(): boolean {
    if (!this.expiresAt) return false;
    return new Date() > this.expiresAt;
  }
}
