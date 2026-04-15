import { Run } from '../entities/run.entity';
import { RunStatus } from '../enums';

describe('Run', () => {
  const createRun = (status = RunStatus.Pending) =>
    new Run({
      runId: 'run-1',
      sessionId: 'session-1',
      status,
      createdAt: new Date(),
    });

  describe('valid transitions', () => {
    it('should transition pending -> ingesting -> analyzing -> synthesizing -> completed', () => {
      const run = createRun();
      run.transitionTo(RunStatus.Ingesting);
      expect(run.status).toBe(RunStatus.Ingesting);
      run.transitionTo(RunStatus.Analyzing);
      expect(run.status).toBe(RunStatus.Analyzing);
      run.transitionTo(RunStatus.Synthesizing);
      expect(run.status).toBe(RunStatus.Synthesizing);
      run.transitionTo(RunStatus.Completed);
      expect(run.status).toBe(RunStatus.Completed);
      expect(run.completedAt).toBeDefined();
    });

    it('should allow cancellation from any active state', () => {
      for (const status of [
        RunStatus.Pending,
        RunStatus.Ingesting,
        RunStatus.Analyzing,
        RunStatus.Synthesizing,
      ]) {
        const run = createRun(status);
        run.transitionTo(RunStatus.Cancelled);
        expect(run.status).toBe(RunStatus.Cancelled);
        expect(run.completedAt).toBeDefined();
      }
    });

    it('should allow failure from any active state', () => {
      for (const status of [
        RunStatus.Pending,
        RunStatus.Ingesting,
        RunStatus.Analyzing,
        RunStatus.Synthesizing,
      ]) {
        const run = createRun(status);
        run.transitionTo(RunStatus.Failed);
        expect(run.status).toBe(RunStatus.Failed);
      }
    });
  });

  describe('simplified workflow transitions', () => {
    it('should allow pending -> completed (simplified pipeline)', () => {
      const run = createRun();
      run.transitionTo(RunStatus.Completed);
      expect(run.status).toBe(RunStatus.Completed);
      expect(run.completedAt).toBeDefined();
    });

    it('should allow ingesting -> completed (early completion)', () => {
      const run = createRun();
      run.transitionTo(RunStatus.Ingesting);
      run.transitionTo(RunStatus.Completed);
      expect(run.status).toBe(RunStatus.Completed);
      expect(run.completedAt).toBeDefined();
    });

    it('should allow analyzing -> completed (partial pipeline)', () => {
      const run = createRun();
      run.transitionTo(RunStatus.Ingesting);
      run.transitionTo(RunStatus.Analyzing);
      run.transitionTo(RunStatus.Completed);
      expect(run.status).toBe(RunStatus.Completed);
      expect(run.completedAt).toBeDefined();
    });
  });

  describe('invalid transitions', () => {
    it('should reject completed -> any', () => {
      const run = createRun();
      run.transitionTo(RunStatus.Ingesting);
      run.transitionTo(RunStatus.Analyzing);
      run.transitionTo(RunStatus.Synthesizing);
      run.transitionTo(RunStatus.Completed);
      expect(() => run.transitionTo(RunStatus.Pending)).toThrow(
        'Invalid run transition',
      );
    });

    it('should reject skipping phases', () => {
      const run = createRun();
      expect(() => run.transitionTo(RunStatus.Analyzing)).toThrow(
        'Invalid run transition',
      );
    });

    it('should reject cancelled -> any', () => {
      const run = createRun();
      run.transitionTo(RunStatus.Cancelled);
      expect(() => run.transitionTo(RunStatus.Pending)).toThrow(
        'Invalid run transition',
      );
    });
  });
});
