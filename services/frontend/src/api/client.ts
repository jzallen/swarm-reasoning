import type { Session, Verdict, ErrorResponse } from './types';

const BASE_URL = '/sessions';

class ApiError extends Error {
  status: number;
  body: ErrorResponse;

  constructor(status: number, body: ErrorResponse) {
    super(body.message || body.error);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }
}

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });

  if (!res.ok) {
    let body: ErrorResponse;
    try {
      body = await res.json();
    } catch {
      body = { error: `HTTP ${res.status}`, message: res.statusText };
    }
    throw new ApiError(res.status, body);
  }

  return res.json() as Promise<T>;
}

export async function createSession(): Promise<Session> {
  return request<Session>(BASE_URL, { method: 'POST' });
}

export async function getSession(sessionId: string): Promise<Session> {
  return request<Session>(`${BASE_URL}/${sessionId}`);
}

export async function submitClaim(
  sessionId: string,
  claimText: string,
): Promise<Session> {
  return request<Session>(`${BASE_URL}/${sessionId}/claims`, {
    method: 'POST',
    body: JSON.stringify({ claimText }),
  });
}

export async function getVerdict(sessionId: string): Promise<Verdict> {
  return request<Verdict>(`${BASE_URL}/${sessionId}/verdict`);
}

export { ApiError };
