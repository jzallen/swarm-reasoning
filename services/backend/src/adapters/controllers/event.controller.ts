import {
  Controller,
  Get,
  GoneException,
  Headers,
  Logger,
  NotFoundException,
  Param,
  Res,
} from '@nestjs/common';
import type { Response } from 'express';
import { StreamProgressUseCase } from '../../application/use-cases/index.js';
import {
  mapProgressTypeToSseEvent,
  isTerminalEvent,
} from '../presenters/sse-event.mapper.js';

const HEARTBEAT_INTERVAL_MS = 30_000;

@Controller('sessions')
export class EventController {
  private readonly logger = new Logger(EventController.name);

  constructor(
    private readonly streamProgressUseCase: StreamProgressUseCase,
  ) {}

  @Get(':sessionId/events')
  async streamEvents(
    @Param('sessionId') sessionId: string,
    @Headers('last-event-id') lastEventId: string | undefined,
    @Res() res: Response,
  ) {
    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('Connection', 'keep-alive');
    res.setHeader('X-Accel-Buffering', 'no');
    res.flushHeaders();

    let clientDisconnected = false;
    res.on('close', () => {
      clientDisconnected = true;
    });

    const heartbeat = setInterval(() => {
      if (!res.writableEnded) {
        res.write(':heartbeat\n\n');
      }
    }, HEARTBEAT_INTERVAL_MS);

    try {
      const stream = this.streamProgressUseCase.execute(
        sessionId,
        lastEventId,
      );

      for await (const event of stream) {
        if (clientDisconnected) break;

        const sseEventName = mapProgressTypeToSseEvent(event.type);
        const data = JSON.stringify({
          runId: event.runId,
          agent: event.agent,
          phase: event.phase,
          type: event.type,
          message: event.message,
          timestamp: event.timestamp.toISOString(),
        });

        res.write(`id: ${event.entryId}\nevent: ${sseEventName}\ndata: ${data}\n\n`);

        if (isTerminalEvent(event.type)) {
          break;
        }
      }
    } catch (error) {
      if (clientDisconnected) return;

      if (error instanceof NotFoundException) {
        res.write(
          `event: error\ndata: ${JSON.stringify({ error: error.message, status: 404 })}\n\n`,
        );
      } else if (error instanceof GoneException) {
        res.write(
          `event: error\ndata: ${JSON.stringify({ error: error.message, status: 410 })}\n\n`,
        );
      } else {
        const message =
          error instanceof Error ? error.message : 'Unknown error';
        this.logger.error(
          `SSE stream error for session ${sessionId}: ${message}`,
        );
        res.write(
          `event: error\ndata: ${JSON.stringify({ error: message, status: 500 })}\n\n`,
        );
      }
    } finally {
      clearInterval(heartbeat);
      if (!res.writableEnded) {
        res.end();
      }
    }
  }
}
