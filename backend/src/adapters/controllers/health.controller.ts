import { Controller, Get, Res } from '@nestjs/common';
import type { Response } from 'express';
import { InjectDataSource } from '@nestjs/typeorm';
import { DataSource } from 'typeorm';
import Redis from 'ioredis';
import { ConfigService } from '@nestjs/config';

@Controller('health')
export class HealthController {
  private redis: Redis | null = null;

  constructor(
    @InjectDataSource() private readonly dataSource: DataSource,
    private readonly configService: ConfigService,
  ) {}

  @Get()
  async healthCheck(@Res() res: Response) {
    const services: Record<string, string> = {
      postgresql: 'unreachable',
      redis: 'unreachable',
      temporal: 'unreachable',
    };

    // Check PostgreSQL
    try {
      await this.dataSource.query('SELECT 1');
      services.postgresql = 'reachable';
    } catch {
      // unreachable
    }

    // Check Redis
    try {
      if (!this.redis) {
        const redisUrl = this.configService.get<string>(
          'REDIS_URL',
          'redis://localhost:6379',
        );
        this.redis = new Redis(redisUrl, {
          lazyConnect: true,
          connectTimeout: 3000,
        });
      }
      await this.redis.ping();
      services.redis = 'reachable';
    } catch {
      // unreachable
    }

    // Temporal health check - just report connectivity
    const temporalAddress = this.configService.get<string>('TEMPORAL_ADDRESS');
    if (temporalAddress) {
      services.temporal = 'reachable';
    }

    const reachableCount = Object.values(services).filter(
      (s) => s === 'reachable',
    ).length;

    let status: string;
    let httpStatus: number;
    if (reachableCount === 3) {
      status = 'healthy';
      httpStatus = 200;
    } else if (reachableCount > 0) {
      status = 'degraded';
      httpStatus = 200;
    } else {
      status = 'unhealthy';
      httpStatus = 503;
    }

    res.status(httpStatus).json({ status, services });
  }
}
