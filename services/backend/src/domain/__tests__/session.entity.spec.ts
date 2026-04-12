import { Session } from '../entities/session.entity';
import { SessionStatus } from '../enums';

describe('Session', () => {
  const createSession = (status = SessionStatus.Active) =>
    new Session({
      sessionId: 'test-id',
      status,
      createdAt: new Date(),
    });

  describe('state transitions', () => {
    it('should transition from active to frozen', () => {
      const session = createSession();
      session.transitionTo(SessionStatus.Frozen);
      expect(session.status).toBe(SessionStatus.Frozen);
      expect(session.frozenAt).toBeDefined();
      expect(session.expiresAt).toBeDefined();
    });

    it('should transition from frozen to expired', () => {
      const session = createSession();
      session.transitionTo(SessionStatus.Frozen);
      session.transitionTo(SessionStatus.Expired);
      expect(session.status).toBe(SessionStatus.Expired);
    });

    it('should reject active -> expired', () => {
      const session = createSession();
      expect(() => session.transitionTo(SessionStatus.Expired)).toThrow(
        'Invalid session transition',
      );
    });

    it('should reject frozen -> active', () => {
      const session = createSession();
      session.transitionTo(SessionStatus.Frozen);
      expect(() => session.transitionTo(SessionStatus.Active)).toThrow(
        'Invalid session transition',
      );
    });

    it('should reject expired -> any', () => {
      const session = createSession();
      session.transitionTo(SessionStatus.Frozen);
      session.transitionTo(SessionStatus.Expired);
      expect(() => session.transitionTo(SessionStatus.Active)).toThrow(
        'Invalid session transition',
      );
      expect(() => session.transitionTo(SessionStatus.Frozen)).toThrow(
        'Invalid session transition',
      );
    });
  });

  describe('isExpired', () => {
    it('should return false when no expiresAt', () => {
      const session = createSession();
      expect(session.isExpired()).toBe(false);
    });

    it('should return true when expiresAt is in the past', () => {
      const session = new Session({
        sessionId: 'test-id',
        status: SessionStatus.Frozen,
        createdAt: new Date(),
        expiresAt: new Date(Date.now() - 1000),
      });
      expect(session.isExpired()).toBe(true);
    });

    it('should return false when expiresAt is in the future', () => {
      const session = new Session({
        sessionId: 'test-id',
        status: SessionStatus.Frozen,
        createdAt: new Date(),
        expiresAt: new Date(Date.now() + 100000),
      });
      expect(session.isExpired()).toBe(false);
    });
  });

  describe('freeze sets TTL', () => {
    it('should set expiresAt to 3 days after frozenAt', () => {
      const session = createSession();
      session.transitionTo(SessionStatus.Frozen);
      const threeDaysMs = 3 * 24 * 60 * 60 * 1000;
      const diff = session.expiresAt!.getTime() - session.frozenAt!.getTime();
      expect(diff).toBe(threeDaysMs);
    });
  });
});
