import { Citation } from '@domain/entities';

export interface CitationRepository {
  saveMany(citations: Citation[]): Promise<Citation[]>;
  findByVerdictId(verdictId: string): Promise<Citation[]>;
}

export const CITATION_REPOSITORY = Symbol('CitationRepository');
