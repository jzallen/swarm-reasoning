import {
  Entity,
  PrimaryColumn,
  Column,
  ManyToOne,
  JoinColumn,
} from 'typeorm';
import { VerdictOrmEntity } from './verdict.orm-entity';

@Entity('citations')
export class CitationOrmEntity {
  @PrimaryColumn('uuid')
  citationId!: string;

  @Column('uuid')
  verdictId!: string;

  @Column({ type: 'varchar', length: 2048 })
  sourceUrl!: string;

  @Column({ type: 'varchar', length: 500 })
  sourceName!: string;

  @Column({ type: 'varchar', length: 100 })
  agent!: string;

  @Column({ type: 'varchar', length: 50 })
  observationCode!: string;

  @Column({ type: 'varchar', length: 20 })
  validationStatus!: string;

  @Column({ type: 'int' })
  convergenceCount!: number;

  @ManyToOne(() => VerdictOrmEntity, (verdict) => verdict.citations, {
    onDelete: 'CASCADE',
  })
  @JoinColumn({ name: 'verdictId' })
  verdict!: VerdictOrmEntity;
}
