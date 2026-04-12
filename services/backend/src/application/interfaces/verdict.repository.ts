import { Verdict } from '../../domain/entities';

export interface VerdictRepository {
  save(verdict: Verdict): Promise<Verdict>;
  findByRunId(runId: string): Promise<Verdict | null>;
}

export const VERDICT_REPOSITORY = Symbol('VerdictRepository');
