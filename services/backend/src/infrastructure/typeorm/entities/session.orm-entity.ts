import {
  Entity,
  PrimaryColumn,
  Column,
  CreateDateColumn,
  OneToMany,
} from 'typeorm';
import { RunOrmEntity } from './run.orm-entity';

@Entity('sessions')
export class SessionOrmEntity {
  @PrimaryColumn('uuid')
  sessionId: string;

  @Column({ type: 'varchar', length: 20 })
  status: string;

  @Column({ type: 'text', nullable: true })
  claim: string | null;

  @CreateDateColumn()
  createdAt: Date;

  @Column({ type: 'timestamptz', nullable: true })
  frozenAt: Date | null;

  @Column({ type: 'timestamptz', nullable: true })
  expiresAt: Date | null;

  @Column({ type: 'varchar', length: 1024, nullable: true })
  snapshotUrl: string | null;

  @OneToMany(() => RunOrmEntity, (run) => run.session)
  runs: RunOrmEntity[];
}
