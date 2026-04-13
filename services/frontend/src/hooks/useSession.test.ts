import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useSession } from './useSession';

// Mock the API client
vi.mock('@/api/client', () => ({
  createSession: vi.fn(),
  getSession: vi.fn(),
  submitClaim: vi.fn(),
  getVerdict: vi.fn(),
}));

import { createSession, getSession, submitClaim, getVerdict } from '@/api/client';

const mockCreateSession = vi.mocked(createSession);
const mockGetSession = vi.mocked(getSession);
const mockSubmitClaim = vi.mocked(submitClaim);
const mockGetVerdict = vi.mocked(getVerdict);

beforeEach(() => {
  vi.resetAllMocks();
  // Reset URL to root so useEffect doesn't try to load a session
  window.history.pushState(null, '', '/');
});

describe('useSession', () => {
  describe('initial state', () => {
    it('starts in idle phase with null values', () => {
      const { result } = renderHook(() => useSession());

      expect(result.current.state.phase).toBe('idle');
      expect(result.current.state.sessionId).toBeNull();
      expect(result.current.state.claim).toBeNull();
      expect(result.current.state.events).toEqual([]);
      expect(result.current.state.verdict).toBeNull();
      expect(result.current.state.snapshotUrl).toBeNull();
      expect(result.current.state.error).toBeNull();
    });
  });

  describe('handleSubmit', () => {
    it('creates a session, submits the claim, and transitions to active', async () => {
      const session = { sessionId: 's-1', status: 'active' as const, createdAt: '2026-01-01' };
      mockCreateSession.mockResolvedValue(session);
      mockSubmitClaim.mockResolvedValue(session);

      const { result } = renderHook(() => useSession());

      await act(async () => {
        await result.current.handleSubmit('The earth is flat');
      });

      expect(mockCreateSession).toHaveBeenCalled();
      expect(mockSubmitClaim).toHaveBeenCalledWith('s-1', 'The earth is flat');
      expect(result.current.state.phase).toBe('active');
      expect(result.current.state.sessionId).toBe('s-1');
      expect(result.current.state.claim).toBe('The earth is flat');
    });

    it('transitions to error on API failure', async () => {
      mockCreateSession.mockRejectedValue(new Error('Network error'));

      const { result } = renderHook(() => useSession());

      await act(async () => {
        await result.current.handleSubmit('Some claim');
      });

      expect(result.current.state.phase).toBe('error');
      expect(result.current.state.error).toBe('Network error');
    });

    it('uses fallback error message for non-Error throws', async () => {
      mockCreateSession.mockRejectedValue('string error');

      const { result } = renderHook(() => useSession());

      await act(async () => {
        await result.current.handleSubmit('Some claim');
      });

      expect(result.current.state.error).toBe('Failed to submit claim');
    });
  });

  describe('handleVerdictReady', () => {
    it('fetches the verdict and transitions to verdict phase', async () => {
      const verdict = {
        verdictId: 'v-1',
        factualityScore: 0.9,
        ratingLabel: 'true' as const,
        narrative: 'Confirmed',
        signalCount: 40,
        citations: [],
        finalizedAt: '2026-01-01',
      };
      mockGetVerdict.mockResolvedValue(verdict);

      const { result } = renderHook(() => useSession());

      await act(async () => {
        await result.current.handleVerdictReady('s-1');
      });

      expect(result.current.state.phase).toBe('verdict');
      expect(result.current.state.verdict).toEqual(verdict);
    });

    it('transitions to error if verdict fetch fails', async () => {
      mockGetVerdict.mockRejectedValue(new Error('Verdict not found'));

      const { result } = renderHook(() => useSession());

      await act(async () => {
        await result.current.handleVerdictReady('s-1');
      });

      expect(result.current.state.phase).toBe('error');
      expect(result.current.state.error).toBe('Verdict not found');
    });
  });

  describe('dispatch actions', () => {
    it('appends progress events', () => {
      const { result } = renderHook(() => useSession());

      act(() => {
        result.current.dispatch({
          type: 'PROGRESS_EVENT',
          event: {
            runId: 'r-1',
            agent: 'ingestion-agent',
            phase: 'ingestion',
            type: 'agent-progress',
            message: 'Processing',
            timestamp: '2026-01-01T00:00:00Z',
          },
        });
      });

      expect(result.current.state.events).toHaveLength(1);
      expect(result.current.state.events[0].agent).toBe('ingestion-agent');
    });

    it('handles SESSION_FROZEN action', () => {
      const { result } = renderHook(() => useSession());

      act(() => {
        result.current.dispatch({
          type: 'SESSION_FROZEN',
          snapshotUrl: 'https://cdn.example.com/snap.html',
        });
      });

      expect(result.current.state.phase).toBe('frozen');
      expect(result.current.state.snapshotUrl).toBe('https://cdn.example.com/snap.html');
    });

    it('handles SESSION_FROZEN without snapshotUrl', () => {
      const { result } = renderHook(() => useSession());

      act(() => {
        result.current.dispatch({ type: 'SESSION_FROZEN' });
      });

      expect(result.current.state.phase).toBe('frozen');
      expect(result.current.state.snapshotUrl).toBeNull();
    });
  });

  describe('URL-based session loading', () => {
    it('loads a frozen session from URL path', async () => {
      const session = {
        sessionId: '12345678-1234-1234-1234-123456789abc',
        status: 'frozen' as const,
        claim: 'Previous claim',
        createdAt: '2026-01-01',
        snapshotUrl: 'https://cdn.example.com/snap.html',
      };
      mockGetSession.mockResolvedValue(session);
      window.history.pushState(null, '', '/12345678-1234-1234-1234-123456789abc');

      const { result } = renderHook(() => useSession());

      // Wait for the effect to complete
      await vi.waitFor(() => {
        expect(result.current.state.phase).toBe('frozen');
      });

      expect(result.current.state.claim).toBe('Previous claim');
      expect(result.current.state.snapshotUrl).toBe('https://cdn.example.com/snap.html');
    });

    it('loads an expired session from URL path', async () => {
      const session = {
        sessionId: '12345678-1234-1234-1234-123456789abc',
        status: 'expired' as const,
        claim: 'Old claim',
        createdAt: '2026-01-01',
      };
      mockGetSession.mockResolvedValue(session);
      window.history.pushState(null, '', '/12345678-1234-1234-1234-123456789abc');

      const { result } = renderHook(() => useSession());

      await vi.waitFor(() => {
        expect(result.current.state.phase).toBe('expired');
      });

      expect(result.current.state.claim).toBe('Old claim');
    });

    it('does not load when path is not a valid UUID', () => {
      window.history.pushState(null, '', '/not-a-uuid');

      renderHook(() => useSession());

      expect(mockGetSession).not.toHaveBeenCalled();
    });
  });
});
