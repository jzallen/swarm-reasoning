import {
  Entity,
  PrimaryColumn,
  Column,
  CreateDateColumn,
  ManyToOne,
  JoinColumn,
  OneToOne,
} from 'typeorm';
import { SessionOrmEntity } from './session.orm-entity';
import { VerdictOrmEntity } from './verdict.orm-entity';

@Entity('runs')
export class RunOrmEntity {
  @PrimaryColumn('uuid')
  runId!: string;

  @Column('uuid')
  sessionId!: string;

  @Column({ type: 'varchar', length: 20 })
  status!: string;

  @Column({ type: 'varchar', length: 50, nullable: true })
  phase!: string | null;

  @CreateDateColumn()
  createdAt!: Date;

  @Column({ type: 'timestamptz', nullable: true })
  completedAt!: Date | null;

  @ManyToOne(() => SessionOrmEntity, (session) => session.runs, {
    onDelete: 'CASCADE',
  })
  @JoinColumn({ name: 'sessionId' })
  session!: SessionOrmEntity;

  @OneToOne(() => VerdictOrmEntity, (verdict) => verdict.run)
  verdict!: VerdictOrmEntity;
}
