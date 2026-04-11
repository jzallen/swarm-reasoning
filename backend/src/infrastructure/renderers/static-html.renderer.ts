import { Injectable } from '@nestjs/common';
import type { Verdict } from '../../domain/entities/verdict.entity.js';
import type { Citation } from '../../domain/entities/citation.entity.js';
import type { Session } from '../../domain/entities/session.entity.js';
import type { ProgressEvent } from '../../domain/entities/progress-event.entity.js';
import { ProgressPhase } from '../../domain/enums/progress-phase.enum.js';
import { ValidationStatus } from '../../domain/enums/validation-status.enum.js';

const PHASE_ORDER: Record<string, number> = {
  [ProgressPhase.Ingestion]: 0,
  [ProgressPhase.Fanout]: 1,
  [ProgressPhase.Synthesis]: 2,
  [ProgressPhase.Finalization]: 3,
};

const PHASE_COLORS: Record<string, string> = {
  [ProgressPhase.Ingestion]: '#2563eb',
  [ProgressPhase.Fanout]: '#7c3aed',
  [ProgressPhase.Synthesis]: '#059669',
  [ProgressPhase.Finalization]: '#d97706',
};

const RATING_COLORS: Record<string, string> = {
  true: '#16a34a',
  'mostly-true': '#65a30d',
  'half-true': '#ca8a04',
  'mostly-false': '#ea580c',
  false: '#dc2626',
  'pants-on-fire': '#991b1b',
};

const STATUS_COLORS: Record<string, string> = {
  [ValidationStatus.Live]: '#16a34a',
  [ValidationStatus.Dead]: '#dc2626',
  [ValidationStatus.Redirect]: '#ca8a04',
  [ValidationStatus.Soft404]: '#ea580c',
  [ValidationStatus.Timeout]: '#9333ea',
  [ValidationStatus.NotValidated]: '#6b7280',
};

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

@Injectable()
export class StaticHtmlRenderer {
  render(
    verdict: Verdict,
    citations: Citation[],
    session: Session,
    progressEvents: ProgressEvent[],
  ): string {
    const sortedCitations = [...citations].sort(
      (a, b) => b.convergenceCount - a.convergenceCount,
    );

    const groupedEvents = this.groupByPhase(progressEvents);

    const ratingColor = RATING_COLORS[verdict.ratingLabel] ?? '#6b7280';
    const scorePercent = Math.round(verdict.factualityScore * 100);

    return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fact Check: ${escapeHtml(session.claim ?? session.sessionId)}</title>
${this.renderStyles(ratingColor)}
</head>
<body>
${this.renderTabBar()}
${this.renderVerdictSection(verdict, sortedCitations, session, ratingColor, scorePercent)}
${this.renderChatSection(groupedEvents)}
${this.renderFooter(session, verdict)}
${this.renderScript()}
</body>
</html>`;
  }

  private renderStyles(ratingColor: string): string {
    return `<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,-apple-system,sans-serif;max-width:900px;margin:0 auto;padding:1rem;color:#1f2937;line-height:1.6;background:#fafafa}
.tab-bar{display:flex;gap:0;border-bottom:2px solid #e5e7eb;margin-bottom:1.5rem}
.tab-btn{padding:.75rem 1.5rem;border:none;background:none;font-size:1rem;cursor:pointer;color:#6b7280;border-bottom:2px solid transparent;margin-bottom:-2px;font-weight:500}
.tab-btn.active{color:#1f2937;border-bottom-color:#2563eb}
.tab-btn:hover{color:#374151}
.section{display:none}
.section.active{display:block}
.kpi{text-align:center;padding:2rem 0}
.score-ring{display:inline-flex;align-items:center;justify-content:center;width:120px;height:120px;border-radius:50%;border:8px solid ${ratingColor};font-size:2.5rem;font-weight:700;color:${ratingColor}}
.rating-badge{display:inline-block;padding:.5rem 1.25rem;border-radius:9999px;font-size:1.1rem;font-weight:600;color:#fff;margin-top:.75rem}
.narrative{background:#fff;border:1px solid #e5e7eb;border-radius:.5rem;padding:1.25rem;margin:1.5rem 0;font-size:.95rem}
.signal-count{color:#6b7280;font-size:.875rem;margin-top:.5rem}
h1{font-size:1.5rem;font-weight:700;margin-bottom:.25rem}
h2{font-size:1.25rem;font-weight:600;margin:1.5rem 0 .75rem;color:#374151}
.claim{font-size:1rem;color:#4b5563;margin-bottom:1rem;font-style:italic}
table{width:100%;border-collapse:collapse;font-size:.875rem;background:#fff;border:1px solid #e5e7eb;border-radius:.5rem;overflow:hidden}
th{background:#f9fafb;text-align:left;padding:.625rem .75rem;font-weight:600;color:#374151;border-bottom:2px solid #e5e7eb}
td{padding:.625rem .75rem;border-bottom:1px solid #f3f4f6}
tr:last-child td{border-bottom:none}
.status-dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:.375rem;vertical-align:middle}
.phase-header{display:flex;align-items:center;gap:.5rem;padding:.5rem 0;margin-top:1rem;border-bottom:1px solid #e5e7eb}
.phase-badge{display:inline-block;padding:.125rem .5rem;border-radius:.25rem;font-size:.75rem;font-weight:600;color:#fff;text-transform:uppercase}
.event-item{display:flex;justify-content:space-between;align-items:flex-start;padding:.5rem 0;border-bottom:1px solid #f3f4f6}
.event-item:last-child{border-bottom:none}
.event-agent{font-weight:600;color:#1f2937;margin-right:.5rem}
.event-msg{color:#4b5563;flex:1}
.event-time{color:#9ca3af;font-size:.75rem;white-space:nowrap;margin-left:1rem}
.print-btn{display:inline-block;padding:.5rem 1rem;background:#2563eb;color:#fff;border:none;border-radius:.375rem;cursor:pointer;font-size:.875rem;margin-top:1rem}
.print-btn:hover{background:#1d4ed8}
footer{margin-top:2rem;padding-top:1rem;border-top:1px solid #e5e7eb;color:#9ca3af;font-size:.75rem;text-align:center}
a{color:#2563eb;text-decoration:none}
a:hover{text-decoration:underline}
@media print{
.tab-bar,.print-btn{display:none!important}
.section{display:block!important}
.section+.section{page-break-before:always}
body{max-width:100%;padding:0}
table{break-inside:avoid}
}
</style>`;
  }

  private renderTabBar(): string {
    return `<div class="tab-bar">
<button class="tab-btn active" onclick="switchTab('verdict')">Verdict</button>
<button class="tab-btn" onclick="switchTab('chat')">Agent Progress</button>
</div>`;
  }

  private renderVerdictSection(
    verdict: Verdict,
    citations: Citation[],
    session: Session,
    ratingColor: string,
    scorePercent: number,
  ): string {
    const citationRows = citations
      .map(
        (c, i) =>
          `<tr>
<td>${i + 1}</td>
<td>${escapeHtml(c.sourceName)}</td>
<td>${escapeHtml(c.agent)}</td>
<td>${escapeHtml(c.observationCode)}</td>
<td><span class="status-dot" style="background:${STATUS_COLORS[c.validationStatus] ?? '#6b7280'}"></span>${escapeHtml(c.validationStatus)}</td>
<td>${c.convergenceCount}</td>
</tr>`,
      )
      .join('\n');

    return `<section id="verdict" class="section active">
<h1>Fact Check Verdict</h1>
<p class="claim">${escapeHtml(session.claim ?? 'N/A')}</p>
<div class="kpi">
<div class="score-ring">${scorePercent}%</div>
<br>
<span class="rating-badge" style="background:${ratingColor}">${escapeHtml(verdict.ratingLabel)}</span>
<p class="signal-count">${verdict.signalCount} signals analyzed</p>
</div>
<h2>Narrative</h2>
<div class="narrative">${escapeHtml(verdict.narrative)}</div>
<h2>Citations</h2>
${
  citations.length > 0
    ? `<table>
<thead><tr><th>#</th><th>Source</th><th>Agent</th><th>Code</th><th>Status</th><th>Cited By</th></tr></thead>
<tbody>${citationRows}</tbody>
</table>`
    : '<p>No citations available.</p>'
}
<button class="print-btn" onclick="window.print()">Print Report</button>
</section>`;
  }

  private renderChatSection(grouped: Map<string, ProgressEvent[]>): string {
    let html =
      '<section id="chat" class="section">\n<h1>Agent Progress Log</h1>\n';

    for (const [phase, events] of grouped) {
      const color = PHASE_COLORS[phase] ?? '#6b7280';
      html += `<div class="phase-header">
<span class="phase-badge" style="background:${color}">${escapeHtml(phase)}</span>
</div>\n`;

      for (const evt of events) {
        const time = evt.timestamp.toISOString().replace('T', ' ').slice(0, 19);
        html += `<div class="event-item">
<div><span class="event-agent">${escapeHtml(evt.agent)}</span><span class="event-msg">${escapeHtml(evt.message)}</span></div>
<span class="event-time">${time}</span>
</div>\n`;
      }
    }

    html += '</section>';
    return html;
  }

  private renderFooter(session: Session, verdict: Verdict): string {
    return `<footer>
<p>Session ${escapeHtml(session.sessionId)} &mdash; Finalized ${verdict.finalizedAt.toISOString()}</p>
</footer>`;
  }

  private renderScript(): string {
    return `<script>
function switchTab(tab){
var sections=document.querySelectorAll('.section');
var buttons=document.querySelectorAll('.tab-btn');
for(var i=0;i<sections.length;i++){sections[i].classList.remove('active')}
for(var i=0;i<buttons.length;i++){buttons[i].classList.remove('active')}
document.getElementById(tab).classList.add('active');
var idx=tab==='verdict'?0:1;
buttons[idx].classList.add('active');
}
</script>`;
  }

  private groupByPhase(events: ProgressEvent[]): Map<string, ProgressEvent[]> {
    const sorted = [...events].sort((a, b) => {
      const phaseA = PHASE_ORDER[a.phase] ?? 99;
      const phaseB = PHASE_ORDER[b.phase] ?? 99;
      if (phaseA !== phaseB) return phaseA - phaseB;
      return a.timestamp.getTime() - b.timestamp.getTime();
    });

    const grouped = new Map<string, ProgressEvent[]>();
    for (const evt of sorted) {
      const phase = evt.phase;
      if (!grouped.has(phase)) {
        grouped.set(phase, []);
      }
      grouped.get(phase)!.push(evt);
    }
    return grouped;
  }
}
