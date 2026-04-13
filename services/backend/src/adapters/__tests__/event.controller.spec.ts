import { NotFoundException, GoneException } from '@nestjs/common';
import { ProgressEvent } from '@domain/entities/progress-event.entity';
import { ProgressPhase, ProgressType } from '@domain/enums';
import { EventController } from '../controllers/event.controller';

function makeEvent(
  type: ProgressType = ProgressType.AgentProgress,
  entryId = '1712736005000-0',
): ProgressEvent {
  return new ProgressEvent({
    runId: 'run-1',
    agent: 'ingestion-agent',
    phase: ProgressPhase.Ingestion,
    type,
    message: 'Processing',
    timestamp: new Date('2024-04-10T12:00:00Z'),
    entryId,
  });
}

function makeMockResponse() {
  const written: string[] = [];
  const headers: Record<string, string> = {};
  return {
    res: {
      setHeader: jest.fn((key: string, val: string) => {
        headers[key] = val;
      }),
      flushHeaders: jest.fn(),
      write: jest.fn((chunk: string) => written.push(chunk)),
      end: jest.fn(),
    },
    written,
    headers,
  };
}

describe('EventController', () => {
  it('should set correct SSE headers including X-Accel-Buffering', async () => {
    async function* emptyStream(): AsyncGenerator<ProgressEvent> {
      // no events
    }

    const mockUseCase = { execute: jest.fn(() => emptyStream()) };
    const controller = new EventController(mockUseCase as any);
    const { res } = makeMockResponse();

    await controller.streamEvents('sess-1', undefined, res as any);

    expect(res.setHeader).toHaveBeenCalledWith(
      'Content-Type',
      'text/event-stream',
    );
    expect(res.setHeader).toHaveBeenCalledWith('Cache-Control', 'no-cache');
    expect(res.setHeader).toHaveBeenCalledWith('Connection', 'keep-alive');
    expect(res.setHeader).toHaveBeenCalledWith('X-Accel-Buffering', 'no');
  });

  it('should format SSE events with id, event name, and data', async () => {
    const event = makeEvent(ProgressType.AgentStarted, '1712736005000-0');

    async function* oneEvent(): AsyncGenerator<ProgressEvent> {
      yield event;
    }

    const mockUseCase = { execute: jest.fn(() => oneEvent()) };
    const controller = new EventController(mockUseCase as any);
    const { res, written } = makeMockResponse();

    await controller.streamEvents('sess-1', undefined, res as any);

    expect(written.length).toBe(1);
    expect(written[0]).toContain('id: 1712736005000-0');
    expect(written[0]).toContain('event: progress');
    expect(written[0]).toContain('"agent":"ingestion-agent"');
  });

  it('should map verdict-ready type to verdict SSE event', async () => {
    const event = makeEvent(ProgressType.VerdictReady, '1712736006000-0');

    async function* verdictStream(): AsyncGenerator<ProgressEvent> {
      yield event;
    }

    const mockUseCase = { execute: jest.fn(() => verdictStream()) };
    const controller = new EventController(mockUseCase as any);
    const { res, written } = makeMockResponse();

    await controller.streamEvents('sess-1', undefined, res as any);

    expect(written[0]).toContain('event: verdict');
    expect(res.end).toHaveBeenCalled();
  });

  it('should map session-frozen type to close SSE event', async () => {
    const event = makeEvent(ProgressType.SessionFrozen, '1712736007000-0');

    async function* closeStream(): AsyncGenerator<ProgressEvent> {
      yield event;
    }

    const mockUseCase = { execute: jest.fn(() => closeStream()) };
    const controller = new EventController(mockUseCase as any);
    const { res, written } = makeMockResponse();

    await controller.streamEvents('sess-1', undefined, res as any);

    expect(written[0]).toContain('event: close');
    expect(res.end).toHaveBeenCalled();
  });

  it('should pass lastEventId to use case', async () => {
    async function* emptyStream(): AsyncGenerator<ProgressEvent> {
      // no events
    }

    const mockUseCase = { execute: jest.fn(() => emptyStream()) };
    const controller = new EventController(mockUseCase as any);
    const { res } = makeMockResponse();

    await controller.streamEvents('sess-1', '1712736005000-0', res as any);

    expect(mockUseCase.execute).toHaveBeenCalledWith(
      'sess-1',
      '1712736005000-0',
    );
  });

  it('should write error event with 404 status for NotFoundException', async () => {
    async function* errorStream(): AsyncGenerator<ProgressEvent> {
      throw new NotFoundException('Session not-found not found');
    }

    const mockUseCase = { execute: jest.fn(() => errorStream()) };
    const controller = new EventController(mockUseCase as any);
    const { res, written } = makeMockResponse();

    await controller.streamEvents('not-found', undefined, res as any);

    expect(written[0]).toContain('event: error');
    expect(written[0]).toContain('"status":404');
    expect(res.end).toHaveBeenCalled();
  });

  it('should write error event with 410 status for GoneException', async () => {
    async function* expiredStream(): AsyncGenerator<ProgressEvent> {
      throw new GoneException('Session expired');
    }

    const mockUseCase = { execute: jest.fn(() => expiredStream()) };
    const controller = new EventController(mockUseCase as any);
    const { res, written } = makeMockResponse();

    await controller.streamEvents('expired-sess', undefined, res as any);

    expect(written[0]).toContain('event: error');
    expect(written[0]).toContain('"status":410');
    expect(res.end).toHaveBeenCalled();
  });

  it('should call res.end() when stream completes', async () => {
    async function* emptyStream(): AsyncGenerator<ProgressEvent> {
      // no events
    }

    const mockUseCase = { execute: jest.fn(() => emptyStream()) };
    const controller = new EventController(mockUseCase as any);
    const { res } = makeMockResponse();

    await controller.streamEvents('sess-1', undefined, res as any);

    expect(res.end).toHaveBeenCalledTimes(1);
  });
});
