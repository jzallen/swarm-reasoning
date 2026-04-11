import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import Redis from 'ioredis';
import { ProgressEvent } from '../../domain/entities/progress-event.entity.js';
import type { StreamReader } from '../../application/interfaces/stream-reader.interface.js';

@Injectable()
export class RedisStreamAdapter implements StreamReader {
  private readonly logger = new Logger(RedisStreamAdapter.name);
  private redis: Redis;

  constructor(private readonly configService: ConfigService) {
    const redisUrl = this.configService.get<string>(
      'REDIS_URL',
      'redis://localhost:6379',
    );
    this.redis = new Redis(redisUrl);
  }

  async *readProgress(
    runId: string,
    lastId = '0-0',
  ): AsyncGenerator<ProgressEvent, void, unknown> {
    const streamKey = `progress:${runId}`;
    let currentId = lastId;

    while (true) {
      try {
        const results = await this.redis.call(
          'XREAD',
          'BLOCK',
          '5000',
          'COUNT',
          '10',
          'STREAMS',
          streamKey,
          currentId,
        ) as [string, [string, string[]][]][] | null;

        if (!results) continue;

        for (const [, entries] of results) {
          for (const [entryId, fields] of entries) {
            currentId = entryId;
            const data = this.parseFields(fields);
            const event = new ProgressEvent({
              runId: data.runId ?? runId,
              agent: data.agent ?? '',
              phase: data.phase ?? '',
              type: (data.type as 'progress' | 'verdict' | 'close') ?? 'progress',
              message: data.message ?? '',
              timestamp: data.timestamp
                ? new Date(data.timestamp)
                : new Date(),
            });

            yield event;

            if (event.type === 'close' || event.type === 'verdict') {
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

  async readObservations(runId: string): Promise<Record<string, unknown>[]> {
    const pattern = `reasoning:${runId}:*`;
    const keys = await this.redis.keys(pattern);
    const observations: Record<string, unknown>[] = [];

    for (const key of keys) {
      const entries = await this.redis.xrange(key, '-', '+');
      for (const [, fields] of entries) {
        const data = this.parseFields(fields);
        observations.push(data);
      }
    }

    return observations;
  }

  private parseFields(fields: string[]): Record<string, string> {
    const data: Record<string, string> = {};
    for (let i = 0; i < fields.length; i += 2) {
      data[fields[i]] = fields[i + 1];
    }
    return data;
  }
}
