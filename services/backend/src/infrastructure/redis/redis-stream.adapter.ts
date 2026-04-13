import { Injectable, Logger, OnModuleDestroy } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import Redis from 'ioredis';
import { v4 as uuidv4 } from 'uuid';
import { ProgressEvent } from '@domain/entities/progress-event.entity.js';
import { ProgressPhase } from '@domain/enums/progress-phase.enum.js';
import { ProgressType } from '@domain/enums/progress-type.enum.js';
import type { StreamReader } from '@app/interfaces/stream-reader.interface.js';

const CONSUMER_GROUP = 'sse-consumers';
const BLOCK_MS = 5000;
const BATCH_SIZE = 10;
const IDLE_TIMEOUT_MS = 30 * 60 * 1000;

@Injectable()
export class RedisStreamAdapter implements StreamReader, OnModuleDestroy {
  private readonly logger = new Logger(RedisStreamAdapter.name);
  private redis: Redis;

  constructor(private readonly configService: ConfigService) {
    const redisUrl = this.configService.get<string>(
      'REDIS_URL',
      'redis://localhost:6379',
    );
    this.redis = new Redis(redisUrl);
  }

  async onModuleDestroy() {
    await this.redis.quit();
  }

  async ping(): Promise<void> {
    await this.redis.ping();
  }

  async *readProgress(
    runId: string,
    lastEventId?: string,
  ): AsyncGenerator<ProgressEvent, void, unknown> {
    const streamKey = `progress:${runId}`;
    const consumerId = `sse-${runId}-${uuidv4()}`;

    await this.ensureConsumerGroup(streamKey);

    try {
      let lastReplayedId: string | undefined;
      if (lastEventId) {
        for await (const event of this.replayFromId(streamKey, lastEventId)) {
          lastReplayedId = event.entryId;
          yield event;
        }
      }

      yield* this.consumeStream(streamKey, consumerId, lastReplayedId);
    } finally {
      await this.removeConsumer(streamKey, consumerId);
    }
  }

  async readObservations(runId: string): Promise<Record<string, unknown>[]> {
    const pattern = `reasoning:${runId}:*`;
    const keys = await this.scanKeys(pattern);
    const observations: Record<string, unknown>[] = [];

    for (const key of keys) {
      const entries = await this.redis.xrange(key, '-', '+');
      for (const [, fields] of entries) {
        const data = this.parseFields(fields);
        observations.push(data);
      }
    }

    observations.sort((a, b) => {
      const tA = typeof a.timestamp === 'string' ? a.timestamp : '';
      const tB = typeof b.timestamp === 'string' ? b.timestamp : '';
      return tA < tB ? -1 : tA > tB ? 1 : 0;
    });

    return observations;
  }

  private async ensureConsumerGroup(streamKey: string): Promise<void> {
    try {
      await this.redis.xgroup(
        'CREATE',
        streamKey,
        CONSUMER_GROUP,
        '0',
        'MKSTREAM',
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : '';
      if (!message.includes('BUSYGROUP')) {
        throw error;
      }
    }
  }

  private async *replayFromId(
    streamKey: string,
    fromId: string,
  ): AsyncGenerator<ProgressEvent, void, unknown> {
    const entries = await this.redis.xrange(
      streamKey,
      this.nextId(fromId),
      '+',
    );

    for (const [entryId, fields] of entries) {
      const event = this.parseEvent(entryId, fields);
      if (!event) continue;
      yield event;
    }
  }

  private async *consumeStream(
    streamKey: string,
    consumerId: string,
    skipBeforeId?: string,
  ): AsyncGenerator<ProgressEvent, void, unknown> {
    let lastActivity = Date.now();

    while (true) {
      if (Date.now() - lastActivity > IDLE_TIMEOUT_MS) {
        this.logger.warn(
          `Idle timeout reached for stream ${streamKey}, consumer ${consumerId}`,
        );
        return;
      }

      try {
        const results = (await this.redis.call(
          'XREADGROUP',
          'GROUP',
          CONSUMER_GROUP,
          consumerId,
          'BLOCK',
          String(BLOCK_MS),
          'COUNT',
          String(BATCH_SIZE),
          'STREAMS',
          streamKey,
          '>',
        )) as [string, [string, string[]][]][] | null;

        if (!results) continue;

        for (const [, entries] of results) {
          for (const [entryId, fields] of entries) {
            lastActivity = Date.now();

            const event = this.parseEvent(entryId, fields);

            await this.redis.xack(streamKey, CONSUMER_GROUP, entryId);

            if (!event) continue;

            if (skipBeforeId && this.compareEntryIds(entryId, skipBeforeId) <= 0) {
              continue;
            }

            yield event;

            if (
              event.type === ProgressType.SessionFrozen ||
              event.type === ProgressType.VerdictReady
            ) {
              return;
            }
          }
        }
      } catch (error) {
        this.logger.error(`Error reading progress stream: ${error}`);
        return;
      }
    }
  }

  private compareEntryIds(a: string, b: string): number {
    const [aTime, aSeq] = a.split('-').map(Number);
    const [bTime, bSeq] = b.split('-').map(Number);
    if (aTime !== bTime) return aTime - bTime;
    return aSeq - bSeq;
  }

  private async removeConsumer(
    streamKey: string,
    consumerId: string,
  ): Promise<void> {
    try {
      await this.redis.xgroup(
        'DELCONSUMER',
        streamKey,
        CONSUMER_GROUP,
        consumerId,
      );
    } catch (error) {
      this.logger.warn(`Failed to remove consumer ${consumerId}: ${error}`);
    }
  }

  private parseEvent(entryId: string, fields: string[]): ProgressEvent | null {
    const data = this.parseFields(fields);

    const type = this.toProgressType(data.type);
    if (!type) {
      this.logger.warn(
        `Unknown progress type "${data.type}" in entry ${entryId}, skipping`,
      );
      return null;
    }

    return new ProgressEvent({
      runId: data.runId ?? '',
      agent: data.agent ?? '',
      phase: this.toProgressPhase(data.phase),
      type,
      message: data.message ?? '',
      timestamp: data.timestamp ? new Date(data.timestamp) : new Date(),
      entryId,
    });
  }

  private toProgressType(value: string | undefined): ProgressType | null {
    if (!value) return null;
    const values = Object.values(ProgressType) as string[];
    return values.includes(value) ? (value as ProgressType) : null;
  }

  private toProgressPhase(value: string | undefined): ProgressPhase {
    if (!value) return ProgressPhase.Ingestion;
    const values = Object.values(ProgressPhase) as string[];
    return values.includes(value)
      ? (value as ProgressPhase)
      : ProgressPhase.Ingestion;
  }

  private nextId(entryId: string): string {
    const parts = entryId.split('-');
    if (parts.length !== 2) return entryId;
    const seq = parseInt(parts[1], 10);
    return `${parts[0]}-${seq + 1}`;
  }

  async readAllProgressEvents(runId: string): Promise<ProgressEvent[]> {
    const streamKey = `progress:${runId}`;
    const events: ProgressEvent[] = [];

    try {
      const entries = await this.redis.xrange(streamKey, '-', '+');

      for (const [entryId, fields] of entries) {
        const event = this.parseEvent(entryId, fields);
        if (event) {
          events.push(event);
        }
      }
    } catch (error) {
      this.logger.warn(
        `Failed to read all progress events for ${runId}: ${error}`,
      );
    }

    return events;
  }

  async deleteStreams(runId: string): Promise<void> {
    try {
      // Delete progress stream
      await this.redis.del(`progress:${runId}`);

      // Delete all reasoning streams
      const pattern = `reasoning:${runId}:*`;
      const keys = await this.scanKeys(pattern);
      if (keys.length > 0) {
        await this.redis.del(...keys);
      }

      this.logger.log(`Deleted ${keys.length + 1} streams for run ${runId}`);
    } catch (error) {
      this.logger.warn(`Failed to delete streams for ${runId}: ${error}`);
    }
  }

  private scanKeys(pattern: string): Promise<string[]> {
    return new Promise((resolve, reject) => {
      const keys: string[] = [];
      const stream = this.redis.scanStream({ match: pattern, count: 100 });
      stream.on('data', (batch: string[]) => {
        keys.push(...batch);
      });
      stream.on('end', () => resolve(keys));
      stream.on('error', reject);
    });
  }

  private parseFields(fields: string[]): Record<string, string> {
    const data: Record<string, string> = {};
    for (let i = 0; i < fields.length; i += 2) {
      data[fields[i]] = fields[i + 1];
    }
    return data;
  }
}
