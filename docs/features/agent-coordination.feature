# feature: agent-coordination
# Covers hub-and-spoke MCP topology enforcement, pull and push interaction
# patterns, OBX append ordering, ACK semantics, completion register
# behaviour, and orchestrator restart recovery.
#
# Compatible with @cucumber/cucumber and jest-cucumber.

Feature: Agent Coordination

  Background:
    Given the orchestrator is running
    And all agent bundles are healthy and registered
    And run "RUN-001" is in ANALYZING state

  # ---------------------------------------------------------------------------
  # Hub-and-Spoke MCP Topology
  # ---------------------------------------------------------------------------

  Scenario: No subagent-to-subagent MCP connections are permitted
    Given coverage-left is executing its task for run "RUN-001"
    When coverage-left requires COVERAGE_* data from coverage-center
    Then coverage-left issues an MCP tool_request to the orchestrator
    And the orchestrator fetches from coverage-center on coverage-left's behalf
    And no direct MCP connection exists between coverage-left and coverage-center

  Scenario: Each subagent exposes get_observations tool
    When the orchestrator calls get_observations on any agent MCP server
    Then the response contains OBX rows scoped to the specified run_id
    And the response includes code, value, units, status, and responsible_observer per row

  Scenario: Each subagent exposes get_terminal_status tool
    When all parallel agents have emitted F-status OBX rows for run "RUN-001"
    And the orchestrator calls get_terminal_status on each agent MCP server
    Then each response returns true

  Scenario: Orchestrator holds all MCP client connections
    Then the MCP connection registry on the orchestrator contains exactly 10 entries
    And each entry corresponds to a registered agent bundle
    And no agent bundle holds an MCP client connection to another agent bundle

  # ---------------------------------------------------------------------------
  # Push Pattern
  # ---------------------------------------------------------------------------

  Scenario: Coverage agent completes task and sends HL7v2 to specified channel
    Given the orchestrator dispatches coverage-left with reply_channel "ORCH_ACK"
    When coverage-left completes its analysis
    Then coverage-left Mirth sends an HL7v2 message to the "ORCH_ACK" channel
    And the message contains F-status OBX rows for COVERAGE_ARTICLE_COUNT
    And the message contains F-status OBX rows for COVERAGE_FRAMING
    And OBX.16 on all rows equals "coverage-left"
    And the orchestrator Mirth channel "ORCH_ACK" receives the message within 30 seconds

  Scenario: Orchestrator marks agent complete on ACK receipt, not on MCP return
    Given the orchestrator dispatches coverage-right with reply_channel "ORCH_ACK"
    When coverage-right's MCP invoke_task call returns task_accepted
    Then the orchestrator completion register does NOT mark coverage-right complete
    When the orchestrator Mirth receives an ACK AA from coverage-right
    Then the orchestrator completion register marks coverage-right complete

  # ---------------------------------------------------------------------------
  # Pull Pattern
  # ---------------------------------------------------------------------------

  Scenario: Blindspot detector requests data via orchestrator
    Given coverage-left, coverage-center, and coverage-right are all complete
    And the orchestrator dispatches blindspot-detector
    When blindspot-detector issues an MCP tool_request for COVERAGE_* observations
    Then the orchestrator fetches COVERAGE_* OBX rows from coverage-left MCP
    And the orchestrator fetches COVERAGE_* OBX rows from coverage-center MCP
    And the orchestrator fetches COVERAGE_* OBX rows from coverage-right MCP
    And the orchestrator returns consolidated rows to blindspot-detector in a single MCP response

  Scenario: Synthesizer receives full consolidated OBX log via MCP
    Given all 10 agents have emitted terminal OBX status for run "RUN-001"
    When the orchestrator dispatches the synthesizer
    Then the MCP invoke_task payload includes OBX rows from all 10 agents
    And the payload contains only F-status and C-status rows
    And no P-status rows are included in the synthesizer payload

  # ---------------------------------------------------------------------------
  # OBX Append Ordering
  # ---------------------------------------------------------------------------

  Scenario: OBX sequence numbers are monotonically increasing within a run
    Given multiple agents have written OBX rows for run "RUN-001"
    When the full OBX log is retrieved from YottaDB
    Then OBX.1 sequence numbers form a gapless ascending integer sequence starting at 1
    And no two OBX rows share the same sequence number

  Scenario: Concurrent agent writes do not produce duplicate sequence numbers
    Given coverage-left, coverage-center, coverage-right, and domain-evidence write OBX rows concurrently
    When all four agents complete
    Then the OBX log for run "RUN-001" contains no duplicate OBX.1 sequence numbers
    And all rows from all four agents are present

  Scenario: Correction row is appended with next sequence number
    Given ingestion-agent wrote CLAIM_DOMAIN = "POLICY" at OBX.1 = 4 with status F
    When an agent writes a correction with CLAIM_DOMAIN = "HEALTHCARE" status C
    Then the correction row has OBX.1 greater than 4
    And the original row at OBX.1 = 4 is unchanged in YottaDB

  # ---------------------------------------------------------------------------
  # ACK Semantics
  # ---------------------------------------------------------------------------

  Scenario: Orchestrator retries on AE application error ACK up to 3 times
    Given the orchestrator sends an HL7v2 message to coverage-left Mirth
    When coverage-left Mirth responds with ACK AE on the first attempt
    Then the orchestrator retries the message delivery
    And the orchestrator retries at most 3 times before escalating to the error log

  Scenario: Orchestrator does not retry on AR application reject ACK
    Given the orchestrator sends an HL7v2 message to coverage-center Mirth
    When coverage-center Mirth responds with ACK AR
    Then the orchestrator does NOT retry
    And the run error log records the AR with the message control ID and reason

  # ---------------------------------------------------------------------------
  # Completion Register and Fan-out Gates
  # ---------------------------------------------------------------------------

  Scenario: Blindspot detector is not dispatched until coverage agents are complete
    Given coverage-left and coverage-center are complete
    But coverage-right has not yet emitted terminal OBX status
    Then the orchestrator does NOT dispatch blindspot-detector

  Scenario: Synthesizer is not dispatched until all 10 agents are complete
    Given 9 of 10 agents have emitted terminal OBX status for run "RUN-001"
    Then the orchestrator does NOT dispatch the synthesizer
    When the tenth agent emits terminal OBX status
    Then the orchestrator dispatches the synthesizer within 5 seconds

  # ---------------------------------------------------------------------------
  # Orchestrator Restart Recovery
  # ---------------------------------------------------------------------------

  Scenario: Orchestrator reconstructs completion state after restart
    Given run "RUN-001" is in ANALYZING state
    And coverage-left, coverage-center, and claimreview-matcher have emitted terminal OBX
    When the orchestrator process restarts
    Then the orchestrator calls get_terminal_status on each agent MCP server
    And the completion register reflects coverage-left, coverage-center, and claimreview-matcher as complete
    And the orchestrator resumes monitoring for the remaining agents
    And no duplicate MCP dispatch is issued to already-complete agents
