## ADDED Requirements

### Requirement: StaticHtmlRenderer produces a self-contained HTML document

The `StaticHtmlRenderer` SHALL accept verdict data, progress events, and session metadata, and produce a self-contained HTML string. The document SHALL include all CSS inline in a `<style>` block, all JavaScript inline in a `<script>` block, and no external resource references. The document SHALL be viewable by opening the HTML file directly in a browser without any server.

#### Scenario: Rendered HTML is a valid document

- **GIVEN** a verdict with factuality score 0.84, rating "mostly-true", narrative text, and 5 citations
- **AND** 20 progress events from 6 agents
- **WHEN** `StaticHtmlRenderer.render(verdict, progressEvents, session)` is called
- **THEN** the output is a valid HTML5 document starting with `<!DOCTYPE html>`
- **AND** the document contains `<html lang="en">`
- **AND** the document contains a `<meta charset="utf-8">` tag
- **AND** the document contains a `<meta name="viewport">` tag

#### Scenario: No external resource references

- **GIVEN** a rendered HTML snapshot
- **WHEN** the document is inspected
- **THEN** no `<link>` elements reference external stylesheets
- **AND** no `<script>` elements reference external JavaScript files
- **AND** no `<img>` elements reference external images
- **AND** all styles are in `<style>` blocks
- **AND** all scripts are in `<script>` blocks

### Requirement: Two toggled views in one HTML document

The rendered HTML SHALL contain two views: a verdict summary section and a chat progress log section. Only one view SHALL be visible at a time, toggled by a tab bar with two buttons. The toggle logic SHALL be implemented in inline JavaScript (~10 lines).

#### Scenario: Verdict view visible by default

- **GIVEN** a rendered HTML snapshot
- **WHEN** the document is opened in a browser
- **THEN** the verdict summary section is visible
- **AND** the chat progress section is hidden
- **AND** the "Verdict" tab button appears active (highlighted)

#### Scenario: Tab toggle switches views

- **GIVEN** a rendered HTML snapshot with the verdict view active
- **WHEN** the user clicks the "Agent Progress" tab button
- **THEN** the verdict section is hidden
- **AND** the chat progress section is visible
- **AND** the "Agent Progress" tab button appears active

#### Scenario: Tab toggle back to verdict

- **GIVEN** a rendered HTML snapshot with the chat progress view active
- **WHEN** the user clicks the "Verdict" tab button
- **THEN** the verdict section is visible
- **AND** the chat progress section is hidden

### Requirement: Verdict view displays score, rating, narrative, and citations

The verdict section SHALL display the factuality score as a prominent KPI, the rating label as a color-coded badge, the narrative explanation as prose text, and the citation table with validation status indicators.

#### Scenario: Factuality score in verdict view

- **GIVEN** a verdict with `factualityScore: 0.72`
- **WHEN** the verdict section renders
- **THEN** the score "0.72" is displayed as a large, prominent number

#### Scenario: Rating badge color in verdict view

- **GIVEN** a verdict with `ratingLabel: "mostly-true"`
- **WHEN** the verdict section renders
- **THEN** a badge with text "Mostly True" is displayed with a green background

#### Scenario: Citation table in verdict view

- **GIVEN** a verdict with 3 citations: [{sourceName: "Reuters", validationStatus: "live", convergenceCount: 3}, {sourceName: "CDC", validationStatus: "live", convergenceCount: 2}, {sourceName: "Example Blog", validationStatus: "dead", convergenceCount: 1}]
- **WHEN** the verdict section renders
- **THEN** a table with 3 rows is displayed
- **AND** rows are ordered by convergence count descending: Reuters (3), CDC (2), Example Blog (1)
- **AND** Reuters and CDC show a green status indicator for "live"
- **AND** Example Blog shows a red status indicator for "dead"

### Requirement: Chat progress view displays agent messages chronologically

The chat progress section SHALL display all progress events in chronological order, grouped by phase (ingestion, fanout, synthesis, finalization). Each event shows the agent name, phase badge, message text, and timestamp.

#### Scenario: Progress events grouped by phase

- **GIVEN** 20 progress events: 3 from ingestion phase, 12 from fanout phase, 5 from synthesis phase
- **WHEN** the chat progress section renders
- **THEN** events are displayed in chronological order
- **AND** phase separator headers appear before the first event of each phase: "Ingestion", "Fan-out", "Synthesis"

#### Scenario: Agent message rendering

- **GIVEN** a progress event `{agent: "coverage-left", phase: "fanout", message: "Found 3 articles from left-leaning sources", timestamp: "2026-04-10T12:00:05Z"}`
- **WHEN** the event is rendered in the chat section
- **THEN** "coverage-left" appears in bold
- **AND** "fanout" appears as a colored badge
- **AND** the message text appears as the body
- **AND** the timestamp appears right-aligned

### Requirement: Print button triggers browser print dialog

The rendered HTML SHALL include a "Print this page" button. Clicking it SHALL call `window.print()`. In print mode, the tab bar and print button SHALL be hidden, and both the verdict and chat sections SHALL be displayed sequentially.

#### Scenario: Print button triggers dialog

- **GIVEN** a rendered HTML snapshot
- **WHEN** the user clicks the "Print this page" button
- **THEN** `window.print()` is called

#### Scenario: Print layout shows both views

- **GIVEN** a rendered HTML snapshot
- **WHEN** the browser print preview renders
- **THEN** the tab bar is hidden
- **AND** the print button is hidden
- **AND** the verdict section is visible
- **AND** the chat progress section is visible below the verdict section
- **AND** a page break separates the two sections

### Requirement: Render time under 5000ms (NFR-030)

The `StaticHtmlRenderer.render()` method SHALL complete within 5000ms for a typical verdict with up to 100 progress events and 20 citations.

#### Scenario: Render time measurement

- **GIVEN** a verdict with 15 citations and 80 progress events
- **WHEN** `render()` is called
- **THEN** the method returns within 5000ms
