import { useReducer, useCallback, useEffect } from "react";
import type { ProgressEvent, Verdict, Session } from "@/api/types";
import {
  createSession,
  getSession,
  submitClaim,
  getVerdict,
} from "@/api/client";

type SessionPhase =
  | "idle"
  | "creating"
  | "active"
  | "verdict"
  | "frozen"
  | "expired"
  | "error";

interface SessionState {
  phase: SessionPhase;
  sessionId: string | null;
  claim: string | null;
  events: ProgressEvent[];
  verdict: Verdict | null;
  snapshotUrl: string | null;
  error: string | null;
  reconnected: boolean;
}

type SessionAction =
  | { type: "SESSION_CREATING" }
  | { type: "SESSION_CREATED"; sessionId: string; claim: string }
  | { type: "SESSION_LOADED"; session: Session }
  | { type: "PROGRESS_EVENT"; event: ProgressEvent }
  | { type: "VERDICT_RECEIVED"; verdict: Verdict }
  | { type: "SESSION_FROZEN"; snapshotUrl?: string | null }
  | { type: "ERROR"; message: string };

const initialState: SessionState = {
  phase: "idle",
  sessionId: null,
  claim: null,
  events: [],
  verdict: null,
  snapshotUrl: null,
  error: null,
  reconnected: false,
};

function sessionReducer(
  state: SessionState,
  action: SessionAction,
): SessionState {
  switch (action.type) {
    case "SESSION_CREATING":
      return { ...state, phase: "creating", error: null };
    case "SESSION_CREATED":
      return {
        ...state,
        phase: "active",
        sessionId: action.sessionId,
        claim: action.claim,
      };
    case "SESSION_LOADED":
      if (action.session.status === "frozen") {
        return {
          ...state,
          phase: "frozen",
          sessionId: action.session.sessionId,
          claim: action.session.claim ?? null,
          snapshotUrl: action.session.snapshotUrl ?? null,
        };
      }
      if (action.session.status === "expired") {
        return {
          ...state,
          phase: "expired",
          sessionId: action.session.sessionId,
          claim: action.session.claim ?? null,
        };
      }
      return {
        ...state,
        phase: "active",
        sessionId: action.session.sessionId,
        claim: action.session.claim ?? null,
        reconnected: true,
      };
    case "PROGRESS_EVENT":
      return { ...state, events: [...state.events, action.event] };
    case "VERDICT_RECEIVED":
      return { ...state, phase: "verdict", verdict: action.verdict };
    case "SESSION_FROZEN":
      return {
        ...state,
        phase: "frozen",
        snapshotUrl: action.snapshotUrl ?? null,
      };
    case "ERROR":
      return { ...state, phase: "error", error: action.message };
  }
}

export function useSession() {
  const [state, dispatch] = useReducer(sessionReducer, initialState);

  const handleSubmit = useCallback(async (claimText: string) => {
    dispatch({ type: "SESSION_CREATING" });
    try {
      const session = await createSession();
      await submitClaim(session.sessionId, claimText);
      window.history.pushState(null, "", `/${session.sessionId}`);
      dispatch({
        type: "SESSION_CREATED",
        sessionId: session.sessionId,
        claim: claimText,
      });
    } catch (err) {
      dispatch({
        type: "ERROR",
        message: err instanceof Error ? err.message : "Failed to submit claim",
      });
    }
  }, []);

  const handleVerdictReady = useCallback(async (sessionId: string) => {
    try {
      const verdict = await getVerdict(sessionId);
      dispatch({ type: "VERDICT_RECEIVED", verdict });
    } catch (err) {
      dispatch({
        type: "ERROR",
        message: err instanceof Error ? err.message : "Failed to load verdict",
      });
    }
  }, []);

  const loadSessionFromUrl = useCallback(() => {
    const pathSessionId = window.location.pathname.replace(/^\//, "");
    if (!pathSessionId || pathSessionId === "") return;

    const uuidRegex =
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
    if (!uuidRegex.test(pathSessionId)) return;

    getSession(pathSessionId)
      .then((session) => {
        dispatch({ type: "SESSION_LOADED", session });
      })
      .catch((err) => {
        dispatch({
          type: "ERROR",
          message: err instanceof Error ? err.message : "Session not found",
        });
      });
  }, []);

  useEffect(() => {
    loadSessionFromUrl();
  }, [loadSessionFromUrl]);

  useEffect(() => {
    const handlePopState = () => {
      loadSessionFromUrl();
    };

    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, [loadSessionFromUrl]);

  return { state, dispatch, handleSubmit, handleVerdictReady };
}

export type { SessionState, SessionAction, SessionPhase };
