import type { Verdict } from '@domain/entities/verdict.entity.js';
import type { Citation } from '@domain/entities/citation.entity.js';
import type { Session } from '@domain/entities/session.entity.js';
import type { ProgressEvent } from '@domain/entities/progress-event.entity.js';

export interface HtmlRenderer {
  render(
    verdict: Verdict,
    citations: Citation[],
    session: Session,
    progressEvents: ProgressEvent[],
  ): string;
}

export const HTML_RENDERER = Symbol('HtmlRenderer');
