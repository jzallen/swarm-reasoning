import { ProgressPhase, ProgressType } from '../../../domain/enums';
import { ProgressEvent } from '../../../domain/entities/progress-event.entity';
import { RedisStreamAdapter } from '../redis-stream.adapter';

jest.mock('uuid', () => ({
  v4: () => 'test-uuid-1234',
}));

describe('RedisStreamAdapter', () => {
  let adapter: RedisStreamAdapter;
  let mockRedis: Record<string, jest.Mock>;

  beforeEach(() => {
    jest.clearAllMocks();

    mockRedis = {
      xgroup: jest.fn(),
      xrange: jest.fn(),
      call: jest.fn(),
      xack: jest.fn(),
      keys: jest.fn(),
      quit: jest.fn(),
    };

    // Create adapter without invoking the real constructor (avoids real Redis connection)
    adapter = Object.create(RedisStreamAdapter.prototype);
    (adapter as any).logger = { error: jest.fn(), warn: jest.fn() };
    (adapter as any).redis = mockRedis;
  });

  function makeEntryFields(
    overrides: Record<string, string> = {},
  ): string[] {
    const fields: Record<string, string> = {
      runId: 'run-1',
      agent: 'ingestion-agent',
      phase: ProgressPhase.Ingestion,
      type: ProgressType.AgentProgress,
      message: 'Processing claim',
      timestamp: '2024-04-10T12:00:00Z',
      ...overrides,
    };
    return Object.entries(fields).flat();
  }

  describe('ensureConsumerGroup', () => {
    it('should create consumer group with MKSTREAM', async () => {
      mockRedis.xgroup.mockResolvedValue('OK');

      const closeFields = makeEntryFields({
        type: ProgressType.SessionFrozen,
      });
      mockRedis.call.mockResolvedValueOnce([
        ['progress:run-1', [['1712736005000-0', closeFields]]],
      ]);
      mockRedis.xack.mockResolvedValue(1);

      for await (const _event of adapter.readProgress('run-1')) {
        // consume
      }

      expect(mockRedis.xgroup).toHaveBeenCalledWith(
        'CREATE',
        'progress:run-1',
        'sse-consumers',
        '0',
        'MKSTREAM',
      );
    });

    it('should ignore BUSYGROUP error (group already exists)', async () => {
      mockRedis.xgroup
        .mockRejectedValueOnce(
          new Error('BUSYGROUP Consumer Group name already exists'),
        )
        .mockResolvedValue(1); // for DELCONSUMER

      const closeFields = makeEntryFields({
        type: ProgressType.SessionFrozen,
      });
      mockRedis.call.mockResolvedValueOnce([
        ['progress:run-1', [['1712736005000-0', closeFields]]],
      ]);
      mockRedis.xack.mockResolvedValue(1);

      // Should not throw
      const events: ProgressEvent[] = [];
      for await (const event of adapter.readProgress('run-1')) {
        events.push(event);
      }
      expect(events).toHaveLength(1);
    });
  });

  describe('readProgress with consumer groups', () => {
    it('should yield events from XREADGROUP', async () => {
      mockRedis.xgroup.mockResolvedValue('OK');
      mockRedis.xack.mockResolvedValue(1);

      mockRedis.call.mockResolvedValueOnce([
        ['progress:run-1', [['1712736005000-0', makeEntryFields()]]],
      ]);

      const closeFields = makeEntryFields({
        type: ProgressType.SessionFrozen,
      });
      mockRedis.call.mockResolvedValueOnce([
        ['progress:run-1', [['1712736006000-0', closeFields]]],
      ]);

      const events: ProgressEvent[] = [];
      for await (const event of adapter.readProgress('run-1')) {
        events.push(event);
      }

      expect(events).toHaveLength(2);
      expect(events[0].type).toBe(ProgressType.AgentProgress);
      expect(events[0].entryId).toBe('1712736005000-0');
      expect(events[1].type).toBe(ProgressType.SessionFrozen);
    });

    it('should call XACK after each entry', async () => {
      mockRedis.xgroup.mockResolvedValue('OK');
      mockRedis.xack.mockResolvedValue(1);

      const closeFields = makeEntryFields({
        type: ProgressType.VerdictReady,
      });
      mockRedis.call.mockResolvedValueOnce([
        ['progress:run-1', [['1712736005000-0', closeFields]]],
      ]);

      for await (const _event of adapter.readProgress('run-1')) {
        // consume
      }

      expect(mockRedis.xack).toHaveBeenCalledWith(
        'progress:run-1',
        'sse-consumers',
        '1712736005000-0',
      );
    });

    it('should use XREADGROUP with correct arguments', async () => {
      mockRedis.xgroup.mockResolvedValue('OK');
      mockRedis.xack.mockResolvedValue(1);

      const closeFields = makeEntryFields({
        type: ProgressType.SessionFrozen,
      });
      mockRedis.call.mockResolvedValueOnce([
        ['progress:run-1', [['1712736005000-0', closeFields]]],
      ]);

      for await (const _event of adapter.readProgress('run-1')) {
        // consume
      }

      expect(mockRedis.call).toHaveBeenCalledWith(
        'XREADGROUP',
        'GROUP',
        'sse-consumers',
        'sse-run-1-test-uuid-1234',
        'BLOCK',
        '5000',
        'COUNT',
        '10',
        'STREAMS',
        'progress:run-1',
        '>',
      );
    });
  });

  describe('replay from lastEventId', () => {
    it('should call XRANGE with incremented ID before consuming', async () => {
      mockRedis.xgroup.mockResolvedValue('OK');
      mockRedis.xack.mockResolvedValue(1);

      const replayFields = makeEntryFields({ message: 'replayed' });
      mockRedis.xrange.mockResolvedValueOnce([
        ['1712736005001-0', replayFields],
      ]);

      const closeFields = makeEntryFields({
        type: ProgressType.SessionFrozen,
      });
      mockRedis.call.mockResolvedValueOnce([
        ['progress:run-1', [['1712736006000-0', closeFields]]],
      ]);

      const events: ProgressEvent[] = [];
      for await (const event of adapter.readProgress(
        'run-1',
        '1712736005000-0',
      )) {
        events.push(event);
      }

      expect(mockRedis.xrange).toHaveBeenCalledWith(
        'progress:run-1',
        '1712736005000-1',
        '+',
      );
      expect(events[0].message).toBe('replayed');
      expect(events).toHaveLength(2);
    });
  });

  describe('consumer cleanup', () => {
    it('should call XGROUP DELCONSUMER when generator returns', async () => {
      mockRedis.xgroup.mockResolvedValue('OK');
      mockRedis.xack.mockResolvedValue(1);

      const closeFields = makeEntryFields({
        type: ProgressType.SessionFrozen,
      });
      mockRedis.call.mockResolvedValueOnce([
        ['progress:run-1', [['1712736005000-0', closeFields]]],
      ]);

      for await (const _event of adapter.readProgress('run-1')) {
        // consume
      }

      expect(mockRedis.xgroup).toHaveBeenCalledWith(
        'DELCONSUMER',
        'progress:run-1',
        'sse-consumers',
        'sse-run-1-test-uuid-1234',
      );
    });
  });

  describe('malformed entries', () => {
    it('should skip entries with unknown progress type', async () => {
      mockRedis.xgroup.mockResolvedValue('OK');
      mockRedis.xack.mockResolvedValue(1);

      const badFields = makeEntryFields({ type: 'unknown-type' });
      const goodFields = makeEntryFields({
        type: ProgressType.SessionFrozen,
      });

      mockRedis.call.mockResolvedValueOnce([
        [
          'progress:run-1',
          [
            ['1712736005000-0', badFields],
            ['1712736006000-0', goodFields],
          ],
        ],
      ]);

      const events: ProgressEvent[] = [];
      for await (const event of adapter.readProgress('run-1')) {
        events.push(event);
      }

      expect(events).toHaveLength(1);
      expect(events[0].type).toBe(ProgressType.SessionFrozen);
      expect(mockRedis.xack).toHaveBeenCalledTimes(2);
    });
  });

  describe('onModuleDestroy', () => {
    it('should quit Redis connection', async () => {
      mockRedis.quit.mockResolvedValue('OK');

      await adapter.onModuleDestroy();

      expect(mockRedis.quit).toHaveBeenCalled();
    });
  });
});
