export interface SnapshotStore {
  upload(sessionId: string, html: string): Promise<string>;
  delete(snapshotUrl: string): Promise<void>;
}

export const SNAPSHOT_STORE = Symbol('SnapshotStore');
