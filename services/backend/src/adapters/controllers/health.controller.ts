import { Controller, Get, Inject, Res } from '@nestjs/common';
import type { Response } from 'express';
import { InjectDataSource } from '@nestjs/typeorm';
import { DataSource } from 'typeorm';
import { ConfigService } from '@nestjs/config';
import type { StreamReader } from '@app/interfaces/stream-reader.interface.js';
import { STREAM_READER } from '@app/interfaces/stream-reader.interface.js';

@Controller('health')
export class HealthController {
  constructor(
    @InjectDataSource() private readonly dataSource: DataSource,
    @Inject(STREAM_READER) private readonly streamReader: StreamReader,
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
      await this.streamReader.ping();
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
      httpStatus = 503;
    } else {
      status = 'unhealthy';
      httpStatus = 503;
    }

    res.status(httpStatus).json({ status, services });
  }
}
