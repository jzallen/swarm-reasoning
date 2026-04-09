# feature: agent-coordination
# Covers hub-and-spoke MCP topology enforcement, pull and push interaction
# patterns, observation append ordering, delivery semantics, completion
# register behaviour, and orchestrator restart recovery.
#
# Compatible with @cucumber/cucumber and jest-cucumber.

Feature: Agent Coordination

  Background:
    Given the orchestrator is running
    And all agents are healthy and registered
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
    Then the response contains observations scoped to the specified run_id
    And the response includes code, value, units, status, and agent per observation

  Scenario: Each subagent exposes get_terminal_status tool
    When all parallel agents have published STOP messages with F-status for run "RUN-001"
    And the orchestrator calls get_terminal_status on each agent MCP server
    Then each response returns true

  Scenario: Orchestrator holds all MCP client connections
    Then the MCP connection registry on the orchestrator contains exactly 10 entries
    And each entry corresponds to a registered agent
    And no agent holds an MCP client connection to another agent

  # ---------------------------------------------------------------------------
  # Push Pattern
  # ---------------------------------------------------------------------------

  Scenario: Coverage agent completes task and publishes observations to its stream
    Given the orchestrator dispatches coverage-left
    When coverage-left completes its analysis
    Then coverage-left publishes observations to stream "reasoning:RUN-001:coverage-left"
    And the stream contains F-status observations for COVERAGE_ARTICLE_COUNT
    And the stream contains F-status observations for COVERAGE_FRAMING
    And the agent field on all observations equals "coverage-left"
    And the stream contains a STOP message within 30 seconds

  Scenario: Orchestrator marks agent complete on STOP receipt, not on MCP return
    Given the orchestrator dispatches coverage-right
    When coverage-right's MCP invoke_task call returns task_accepted
    Then the orchestrator completion register does NOT mark coverage-right complete
    When the orchestrator receives a STOP message from coverage-right via XREADGROUP
    Then the orchestrator completion register marks coverage-right complete

  # ---------------------------------------------------------------------------
  # Pull Pattern
  # ---------------------------------------------------------------------------

  Scenario: Blindspot detector requests data via orchestrator
    Given coverage-left, coverage-center, and coverage-right are all complete
    And the orchestrator dispatches blindspot-detector
    When blindspot-detector issues an MCP tool_request for COVERAGE_* observations
    Then the orchestrator reads COVERAGE_* observations from the coverage-left Redis Stream
    And the orchestrator reads COVERAGE_* observations from the coverage-center Redis Stream
    And the orchestrator reads COVERAGE_* observations from the coverage-right Redis Stream
    And the orchestrator returns consolidated observations to blindspot-detector in a single MCP response

  Scenario: Synthesizer receives full consolidated observation log via MCP
    Given all 10 agents have published STOP messages for run "RUN-001"
    When the orchestrator dispatches the synthesizer
    Then the MCP invoke_task payload includes observations from all 10 agents
    And the payload contains only F-status and C-status observations
    And no P-status observations are included in the synthesizer payload

  # ---------------------------------------------------------------------------
  # Observation Append Ordering
  # ---------------------------------------------------------------------------

  Scenario: Observation sequence numbers are monotonically increasing within a stream
    Given multiple observations have been published to a single agent stream for run "RUN-001"
    When the full observation log is retrieved via XRANGE
    Then seq numbers form a gapless ascending integer sequence starting at 1
    And no two observations share the same seq number

  Scenario: Concurrent agent writes do not produce conflicts
    Given coverage-left, coverage-center, coverage-right, and domain-evidence publish observations concurrently
    When all four agents complete
    Then each agent's stream contains its observations with unique seq numbers
    And all observations from all four agents are present across their respective streams

  Scenario: Correction observation is appended with next sequence number
    Given ingestion-agent published CLAIM_DOMAIN = "POLICY" at seq = 4 with status F
    When an agent publishes a correction with CLAIM_DOMAIN = "HEALTHCARE" status C
    Then the correction observation has seq greater than 4
    And the original observation at seq = 4 is unchanged in the Redis Stream

  # ---------------------------------------------------------------------------
  # Delivery Semantics
  # ---------------------------------------------------------------------------

  Scenario: Orchestrator reclaims unacknowledged stream entries after recovery
    Given the orchestrator crashes while processing observations from coverage-left
    When the orchestrator restarts
    Then unacknowledged entries are visible via XPENDING
    And the orchestrator reclaims them via XCLAIM
    And the reclaimed entries are processed without duplication

  Scenario: Agent publish failure is retried with backoff
    Given Redis is temporarily unreachable from coverage-center
    When coverage-center attempts to publish an observation
    Then coverage-center retries the publish up to 3 times with backoff
    And if all retries fail, the agent reports an error to the orchestrator via MCP

  # ---------------------------------------------------------------------------
  # Completion Register and Fan-out Gates
  # ---------------------------------------------------------------------------

  Scenario: Blindspot detector is not dispatched until coverage agents are complete
    Given coverage-left and coverage-center are complete
    But coverage-right has not yet published a STOP message
    Then the orchestrator does NOT dispatch blindspot-detector

  Scenario: Synthesizer is not dispatched until all preceding agents are complete
    Given 8 of 9 preceding agents have published STOP messages for run "RUN-001"
    Then the orchestrator does NOT dispatch the synthesizer
    When the ninth agent publishes its STOP message
    Then the orchestrator dispatches the synthesizer within 5 seconds

  # ---------------------------------------------------------------------------
  # Orchestrator Restart Recovery
  # ---------------------------------------------------------------------------

  Scenario: Orchestrator reconstructs completion state after restart
    Given run "RUN-001" is in ANALYZING state
    And coverage-left, coverage-center, and claimreview-matcher have published STOP messages
    When the orchestrator process restarts
    Then the orchestrator scans Redis Streams for STOP messages in run "RUN-001"
    And the completion register reflects coverage-left, coverage-center, and claimreview-matcher as complete
    And the orchestrator resumes monitoring for the remaining agents
    And no duplicate MCP dispatch is issued to already-complete agents
