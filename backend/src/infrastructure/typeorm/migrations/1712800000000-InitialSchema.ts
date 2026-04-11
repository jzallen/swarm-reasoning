import { MigrationInterface, QueryRunner } from 'typeorm';

export class InitialSchema1712800000000 implements MigrationInterface {
  name = 'InitialSchema1712800000000';

  public async up(queryRunner: QueryRunner): Promise<void> {
    await queryRunner.query(`
      CREATE TABLE "sessions" (
        "sessionId" uuid NOT NULL,
        "status" varchar(20) NOT NULL DEFAULT 'active',
        "claim" text,
        "createdAt" TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
        "frozenAt" TIMESTAMP WITH TIME ZONE,
        "expiresAt" TIMESTAMP WITH TIME ZONE,
        "snapshotUrl" varchar(1024),
        CONSTRAINT "PK_sessions" PRIMARY KEY ("sessionId")
      )
    `);

    await queryRunner.query(`
      CREATE TABLE "runs" (
        "runId" uuid NOT NULL,
        "sessionId" uuid NOT NULL,
        "status" varchar(20) NOT NULL DEFAULT 'pending',
        "phase" varchar(50),
        "createdAt" TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
        "completedAt" TIMESTAMP WITH TIME ZONE,
        CONSTRAINT "PK_runs" PRIMARY KEY ("runId"),
        CONSTRAINT "FK_runs_session" FOREIGN KEY ("sessionId")
          REFERENCES "sessions"("sessionId") ON DELETE CASCADE
      )
    `);

    await queryRunner.query(`
      CREATE TABLE "verdicts" (
        "verdictId" uuid NOT NULL,
        "runId" uuid NOT NULL,
        "factualityScore" decimal(4,3) NOT NULL,
        "ratingLabel" varchar(20) NOT NULL,
        "narrative" text NOT NULL,
        "signalCount" int NOT NULL,
        "finalizedAt" TIMESTAMP WITH TIME ZONE NOT NULL,
        CONSTRAINT "PK_verdicts" PRIMARY KEY ("verdictId"),
        CONSTRAINT "FK_verdicts_run" FOREIGN KEY ("runId")
          REFERENCES "runs"("runId") ON DELETE CASCADE,
        CONSTRAINT "UQ_verdicts_runId" UNIQUE ("runId")
      )
    `);

    await queryRunner.query(`
      CREATE TABLE "citations" (
        "citationId" uuid NOT NULL,
        "verdictId" uuid NOT NULL,
        "sourceUrl" varchar(2048) NOT NULL,
        "sourceName" varchar(500) NOT NULL,
        "agent" varchar(100) NOT NULL,
        "observationCode" varchar(50) NOT NULL,
        "validationStatus" varchar(20) NOT NULL,
        "convergenceCount" int NOT NULL,
        CONSTRAINT "PK_citations" PRIMARY KEY ("citationId"),
        CONSTRAINT "FK_citations_verdict" FOREIGN KEY ("verdictId")
          REFERENCES "verdicts"("verdictId") ON DELETE CASCADE
      )
    `);

    // Indexes per task 5.6
    await queryRunner.query(
      `CREATE INDEX "IDX_sessions_status_frozenAt" ON "sessions" ("status", "frozenAt")`,
    );
    await queryRunner.query(
      `CREATE INDEX "IDX_runs_sessionId" ON "runs" ("sessionId")`,
    );
    await queryRunner.query(
      `CREATE INDEX "IDX_verdicts_runId" ON "verdicts" ("runId")`,
    );
    await queryRunner.query(
      `CREATE INDEX "IDX_citations_verdictId" ON "citations" ("verdictId")`,
    );
  }

  public async down(queryRunner: QueryRunner): Promise<void> {
    await queryRunner.query(`DROP TABLE "citations"`);
    await queryRunner.query(`DROP TABLE "verdicts"`);
    await queryRunner.query(`DROP TABLE "runs"`);
    await queryRunner.query(`DROP TABLE "sessions"`);
  }
}
