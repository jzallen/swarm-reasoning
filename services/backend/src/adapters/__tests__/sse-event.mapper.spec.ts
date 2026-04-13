import { ProgressType } from '@domain/enums';
import {
  mapProgressTypeToSseEvent,
  isTerminalEvent,
} from '../presenters/sse-event.mapper';

describe('SseEventMapper', () => {
  describe('mapProgressTypeToSseEvent', () => {
    it('should map agent-started to progress', () => {
      expect(mapProgressTypeToSseEvent(ProgressType.AgentStarted)).toBe(
        'progress',
      );
    });

    it('should map agent-progress to progress', () => {
      expect(mapProgressTypeToSseEvent(ProgressType.AgentProgress)).toBe(
        'progress',
      );
    });

    it('should map agent-completed to progress', () => {
      expect(mapProgressTypeToSseEvent(ProgressType.AgentCompleted)).toBe(
        'progress',
      );
    });

    it('should map verdict-ready to verdict', () => {
      expect(mapProgressTypeToSseEvent(ProgressType.VerdictReady)).toBe(
        'verdict',
      );
    });

    it('should map session-frozen to close', () => {
      expect(mapProgressTypeToSseEvent(ProgressType.SessionFrozen)).toBe(
        'close',
      );
    });
  });

  describe('isTerminalEvent', () => {
    it('should return true for verdict-ready', () => {
      expect(isTerminalEvent(ProgressType.VerdictReady)).toBe(true);
    });

    it('should return true for session-frozen', () => {
      expect(isTerminalEvent(ProgressType.SessionFrozen)).toBe(true);
    });

    it('should return false for agent-started', () => {
      expect(isTerminalEvent(ProgressType.AgentStarted)).toBe(false);
    });

    it('should return false for agent-progress', () => {
      expect(isTerminalEvent(ProgressType.AgentProgress)).toBe(false);
    });

    it('should return false for agent-completed', () => {
      expect(isTerminalEvent(ProgressType.AgentCompleted)).toBe(false);
    });
  });
});
