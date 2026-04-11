import { Injectable, Logger } from '@nestjs/common';
import { promises as fs } from 'fs';
import { join } from 'path';
import { SnapshotStore } from '../../application/interfaces';

@Injectable()
export class LocalSnapshotStore implements SnapshotStore {
  private readonly logger = new Logger(LocalSnapshotStore.name);
  private readonly snapshotDir: string;

  constructor() {
    this.snapshotDir = join(process.cwd(), 'snapshots');
  }

  async upload(sessionId: string, html: string): Promise<string> {
    await fs.mkdir(this.snapshotDir, { recursive: true });
    const filename = `${sessionId}.html`;
    const filepath = join(this.snapshotDir, filename);
    await fs.writeFile(filepath, html, 'utf-8');
    this.logger.log(`Snapshot saved: ${filepath}`);
    return `/snapshots/${filename}`;
  }

  async delete(snapshotUrl: string): Promise<void> {
    const filename = snapshotUrl.replace('/snapshots/', '');
    const filepath = join(this.snapshotDir, filename);
    try {
      await fs.unlink(filepath);
      this.logger.log(`Snapshot deleted: ${filepath}`);
    } catch {
      this.logger.warn(`Snapshot not found for deletion: ${filepath}`);
    }
  }
}
