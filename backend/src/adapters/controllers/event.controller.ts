import { Controller, Get, Param, Res } from '@nestjs/common';
import type { Response } from 'express';
import { StreamProgressUseCase } from '../../application/use-cases/index.js';

@Controller('sessions')
export class EventController {
  constructor(
    private readonly streamProgressUseCase: StreamProgressUseCase,
  ) {}

  @Get(':sessionId/events')
  async streamEvents(
    @Param('sessionId') sessionId: string,
    @Res() res: Response,
  ) {
    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('Connection', 'keep-alive');
    res.flushHeaders();

    try {
      const stream = this.streamProgressUseCase.execute(sessionId);
      for await (const event of stream) {
        const data = JSON.stringify({
          runId: event.runId,
          agent: event.agent,
          phase: event.phase,
          type: event.type,
          message: event.message,
          timestamp: event.timestamp.toISOString(),
        });
        res.write(`event: ${event.type}\ndata: ${data}\n\n`);

        if (event.type === 'close' || event.type === 'verdict') {
          break;
        }
      }
    } catch (error) {
      const message =
        error instanceof Error ? error.message : 'Unknown error';
      res.write(
        `event: error\ndata: ${JSON.stringify({ error: message })}\n\n`,
      );
    } finally {
      res.end();
    }
  }
}
