## ADDED Requirements

### Requirement: Verdict display renders factuality score, rating label, narrative, and citations

When the `verdict` SSE event is received, the frontend SHALL render a verdict display below the chat progress log. The display SHALL include a factuality score KPI card, a color-coded rating label badge, the narrative explanation, and a citation table.

#### Scenario: Factuality score rendered as KPI

- **GIVEN** a verdict with `factualityScore: 0.84`
- **WHEN** the verdict display renders
- **THEN** the score "0.84" is displayed as a prominent number
- **AND** the number is visually emphasized (large font size, bold)

#### Scenario: Rating label rendered as color-coded badge

- **GIVEN** a verdict with `ratingLabel: "mostly-true"`
- **WHEN** the verdict display renders
- **THEN** a badge with text "Mostly True" is displayed
- **AND** the badge has a green background color

#### Scenario: Rating label color mapping

| Rating Label | Badge Color | Badge Text |
|---|---|---|
| `true` | Green | True |
| `mostly-true` | Green | Mostly True |
| `half-true` | Yellow/Amber | Half True |
| `mostly-false` | Orange | Mostly False |
| `false` | Red | False |
| `pants-on-fire` | Red | Pants on Fire |

#### Scenario: Narrative explanation rendered as text

- **GIVEN** a verdict with `narrative: "The claim that unemployment reached..."`
- **WHEN** the verdict display renders
- **THEN** the narrative is displayed as a paragraph of text below the score and rating badge

#### Scenario: Signal count displayed as secondary metric

- **GIVEN** a verdict with `signalCount: 24`
- **WHEN** the verdict display renders
- **THEN** the text "Based on 24 signals from 11 agents" is displayed

### Requirement: Citation table displays sources with validation status indicators

The citation table SHALL render all citations from the verdict as a table with columns for source name, URL, discovering agent, observation code, validation status, and convergence count. Citations SHALL be sorted by convergence count descending.

#### Scenario: Citation table columns

- **GIVEN** a verdict with 5 citations
- **WHEN** the citation table renders
- **THEN** the table has columns: Source, URL, Agent, Code, Status, Cited By
- **AND** 5 rows are displayed

#### Scenario: Source URL is a clickable link

- **GIVEN** a citation with `sourceUrl: "https://www.reuters.com/article/123"`
- **WHEN** the citation row renders
- **THEN** the URL is a clickable link
- **AND** the link opens in a new tab (`target="_blank"`)
- **AND** the link has `rel="noopener noreferrer"`

#### Scenario: Validation status indicators

| Validation Status | Icon Color | Label |
|---|---|---|
| `live` | Green | Live |
| `dead` | Red | Dead |
| `redirect` | Yellow | Redirect |
| `soft-404` | Yellow | Soft 404 |
| `timeout` | Yellow | Timeout |
| `not-validated` | Gray | Not Validated |

#### Scenario: Citations sorted by convergence count

- **GIVEN** citations with convergence counts [1, 3, 2, 5, 1]
- **WHEN** the citation table renders
- **THEN** the rows are ordered: 5, 3, 2, 1, 1 (descending)

#### Scenario: Mobile citation table scrolls horizontally

- **GIVEN** a viewport width of 375px
- **WHEN** the citation table renders
- **THEN** the table is wrapped in a horizontally scrollable container

### Requirement: Frozen session displays static HTML snapshot

When the session status is `frozen` and a `snapshotUrl` is available, the frontend SHALL display the static HTML snapshot instead of the live chat interface. The snapshot is rendered in an iframe.

#### Scenario: Frozen session renders snapshot iframe

- **GIVEN** a session with status `frozen` and `snapshotUrl: "/snapshots/{sessionId}.html"`
- **WHEN** the frontend loads
- **THEN** an iframe is rendered with `src="/snapshots/{sessionId}.html"`
- **AND** the iframe fills the content area

#### Scenario: Expired session shows expiration message

- **GIVEN** a session with status `expired`
- **WHEN** the frontend loads
- **THEN** the message "This session has expired. Results are retained for 3 days." is displayed
- **AND** no iframe or chat interface is shown

### Requirement: Print button triggers browser print dialog

A print button SHALL be displayed when the verdict is shown or when viewing a frozen session. Clicking the button SHALL call `window.print()`. The button itself SHALL be hidden in print output via `@media print` CSS.

#### Scenario: Print button visible with verdict

- **GIVEN** a verdict has been received and displayed
- **WHEN** the user views the page
- **THEN** a "Print" button is visible

#### Scenario: Print button triggers print dialog

- **GIVEN** the print button is visible
- **WHEN** the user clicks the print button
- **THEN** `window.print()` is called

#### Scenario: Print button hidden in print output

- **GIVEN** `window.print()` has been triggered
- **WHEN** the print preview renders
- **THEN** the print button is not visible in the print output
