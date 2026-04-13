import { ProgressEvent } from '../../domain/entities';

export interface StreamReader {
  readProgress(
    runId: string,
    lastId?: string,
  ): AsyncGenerator<ProgressEvent, void, unknown>;
  readObservations(runId: string): Promise<Record<string, unknown>[]>;
  readAllProgressEvents(runId: string): Promise<ProgressEvent[]>;
  deleteStreams(runId: string): Promise<void>;
  ping(): Promise<void>;
}

export const STREAM_READER = Symbol('StreamReader');
