import { Run } from '../../domain/entities';

export interface RunRepository {
  save(run: Run): Promise<Run>;
  findById(runId: string): Promise<Run | null>;
  findBySessionId(sessionId: string): Promise<Run | null>;
}

export const RUN_REPOSITORY = Symbol('RunRepository');
