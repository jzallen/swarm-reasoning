import { describe, it, expect, vi, beforeEach } from 'vitest';
import { createSession, getSession, submitClaim, getVerdict, ApiError } from './client';

const mockFetch = vi.fn();
globalThis.fetch = mockFetch;

function jsonResponse(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? 'OK' : 'Error',
    json: () => Promise.resolve(body),
  };
}

beforeEach(() => {
  mockFetch.mockReset();
});

describe('createSession', () => {
  it('POSTs to /sessions and returns the session', async () => {
    const session = { sessionId: 's-1', status: 'active', createdAt: '2026-04-13T00:00:00Z' };
    mockFetch.mockResolvedValueOnce(jsonResponse(session));

    const result = await createSession();

    expect(result).toEqual(session);
    expect(mockFetch).toHaveBeenCalledWith('/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
  });
});

describe('getSession', () => {
  it('GETs /sessions/:id and returns the session', async () => {
    const session = { sessionId: 's-1', status: 'frozen', createdAt: '2026-04-13T00:00:00Z' };
    mockFetch.mockResolvedValueOnce(jsonResponse(session));

    const result = await getSession('s-1');

    expect(result).toEqual(session);
    expect(mockFetch).toHaveBeenCalledWith('/sessions/s-1', {
      headers: { 'Content-Type': 'application/json' },
    });
  });
});

describe('submitClaim', () => {
  it('POSTs to /sessions/:id/claims with the claim text', async () => {
    const session = { sessionId: 's-1', status: 'active', createdAt: '2026-04-13T00:00:00Z' };
    mockFetch.mockResolvedValueOnce(jsonResponse(session));

    const result = await submitClaim('s-1', 'The earth is round');

    expect(result).toEqual(session);
    expect(mockFetch).toHaveBeenCalledWith('/sessions/s-1/claims', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ claimText: 'The earth is round' }),
    });
  });
});

describe('getVerdict', () => {
  it('GETs /sessions/:id/verdict and returns the verdict', async () => {
    const verdict = { verdictId: 'v-1', factualityScore: 0.9 };
    mockFetch.mockResolvedValueOnce(jsonResponse(verdict));

    const result = await getVerdict('s-1');

    expect(result).toEqual(verdict);
    expect(mockFetch).toHaveBeenCalledWith('/sessions/s-1/verdict', {
      headers: { 'Content-Type': 'application/json' },
    });
  });
});

describe('error handling', () => {
  it('throws ApiError with parsed JSON error body on non-ok response', async () => {
    const errorBody = { error: 'Not Found', message: 'Session not found' };
    mockFetch.mockResolvedValueOnce(jsonResponse(errorBody, 404));

    await expect(getSession('bad-id')).rejects.toThrow(ApiError);

    mockFetch.mockResolvedValueOnce(jsonResponse(errorBody, 404));
    const error = await getSession('bad-id').catch((e) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(404);
    expect(error.body).toEqual(errorBody);
    expect(error.message).toBe('Session not found');
  });

  it('creates fallback error body when response JSON parsing fails', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
      json: () => Promise.reject(new Error('not json')),
    });

    try {
      await getSession('s-1');
      expect.unreachable('Should have thrown');
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).status).toBe(500);
      expect((err as ApiError).body).toEqual({
        error: 'HTTP 500',
        message: 'Internal Server Error',
      });
    }
  });
});
