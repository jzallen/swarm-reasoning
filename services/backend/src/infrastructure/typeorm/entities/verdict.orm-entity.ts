import {
  Entity,
  PrimaryColumn,
  Column,
  OneToOne,
  JoinColumn,
  OneToMany,
} from 'typeorm';
import { RunOrmEntity } from './run.orm-entity';
import { CitationOrmEntity } from './citation.orm-entity';

@Entity('verdicts')
export class VerdictOrmEntity {
  @PrimaryColumn('uuid')
  verdictId!: string;

  @Column('uuid')
  runId!: string;

  @Column({ type: 'decimal', precision: 4, scale: 3 })
  factualityScore!: number;

  @Column({ type: 'varchar', length: 20 })
  ratingLabel!: string;

  @Column({ type: 'text' })
  narrative!: string;

  @Column({ type: 'int' })
  signalCount!: number;

  @Column({ type: 'timestamptz' })
  finalizedAt!: Date;

  @OneToOne(() => RunOrmEntity, (run) => run.verdict, { onDelete: 'CASCADE' })
  @JoinColumn({ name: 'runId' })
  run!: RunOrmEntity;

  @OneToMany(() => CitationOrmEntity, (citation) => citation.verdict)
  citations!: CitationOrmEntity[];
}
