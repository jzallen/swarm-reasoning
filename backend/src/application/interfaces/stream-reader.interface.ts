import { ProgressEvent } from '../../domain/entities';

export interface StreamReader {
  readProgress(
    runId: string,
    lastId?: string,
  ): AsyncGenerator<ProgressEvent, void, unknown>;
  readObservations(runId: string): Promise<Record<string, unknown>[]>;
}

export const STREAM_READER = Symbol('StreamReader');
