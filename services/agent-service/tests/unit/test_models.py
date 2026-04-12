"""Unit tests for observation models, status transitions, and stream messages."""

import json

import pytest
from pydantic import TypeAdapter, ValidationError

from swarm_reasoning.models.observation import (
    Observation,
    ObservationCode,
    ValueType,
    get_code_metadata,
)
from swarm_reasoning.models.status import (
    EpistemicStatus,
    InvalidStatusTransition,
    validate_status_transition,
)
from swarm_reasoning.models.stream import (
    ObsMessage,
    Phase,
    StartMessage,
    StopMessage,
    StreamMessage,
)

# ── ObservationCode enum ──────────────────────────────────────────────


class TestObservationCode:
    def test_all_36_codes_present(self):
        assert len(ObservationCode) == 36

    def test_all_codes_have_metadata(self):
        for code in ObservationCode:
            meta = get_code_metadata(code)
            assert "display" in meta
            assert "owner_agent" in meta
            assert "value_type" in meta
            assert isinstance(meta["value_type"], ValueType)

    def test_unknown_code_rejected(self):
        with pytest.raises(ValueError):
            ObservationCode("UNKNOWN_CODE")


# ── EpistemicStatus ───────────────────────────────────────────────────


class TestEpistemicStatus:
    def test_values(self):
        assert EpistemicStatus.PRELIMINARY.value == "P"
        assert EpistemicStatus.FINAL.value == "F"
        assert EpistemicStatus.CORRECTED.value == "C"
        assert EpistemicStatus.CANCELLED.value == "X"

    def test_valid_transition_p_to_f(self):
        validate_status_transition(EpistemicStatus.PRELIMINARY, EpistemicStatus.FINAL)

    def test_valid_transition_p_to_x(self):
        validate_status_transition(EpistemicStatus.PRELIMINARY, EpistemicStatus.CANCELLED)

    def test_valid_transition_f_to_c(self):
        validate_status_transition(EpistemicStatus.FINAL, EpistemicStatus.CORRECTED)

    def test_valid_transition_c_to_c(self):
        validate_status_transition(EpistemicStatus.CORRECTED, EpistemicStatus.CORRECTED)

    def test_invalid_transition_f_to_p(self):
        with pytest.raises(InvalidStatusTransition):
            validate_status_transition(EpistemicStatus.FINAL, EpistemicStatus.PRELIMINARY)

    def test_invalid_transition_x_to_f(self):
        with pytest.raises(InvalidStatusTransition):
            validate_status_transition(EpistemicStatus.CANCELLED, EpistemicStatus.FINAL)

    def test_invalid_transition_p_to_c(self):
        with pytest.raises(InvalidStatusTransition):
            validate_status_transition(EpistemicStatus.PRELIMINARY, EpistemicStatus.CORRECTED)

    def test_invalid_transition_f_to_f(self):
        with pytest.raises(InvalidStatusTransition):
            validate_status_transition(EpistemicStatus.FINAL, EpistemicStatus.FINAL)


# ── Observation model ─────────────────────────────────────────────────


def _make_obs(**overrides) -> dict:
    """Helper to build a valid observation dict."""
    base = {
        "runId": "test-run-001",
        "agent": "ingestion-agent",
        "seq": 1,
        "code": "CLAIM_TEXT",
        "value": "The earth is round",
        "valueType": "ST",
        "units": None,
        "referenceRange": None,
        "status": "P",
        "timestamp": "2026-04-06T12:00:00Z",
        "method": "extract_claim",
        "note": None,
    }
    base.update(overrides)
    return base


class TestObservation:
    def test_valid_st_observation(self):
        obs = Observation(**_make_obs())
        assert obs.code == ObservationCode.CLAIM_TEXT
        assert obs.value_type == ValueType.ST
        assert obs.seq == 1

    def test_serialization_round_trip(self):
        obs = Observation(**_make_obs())
        json_str = obs.model_dump_json(by_alias=True)
        parsed = json.loads(json_str)
        assert parsed["runId"] == "test-run-001"
        assert parsed["code"] == "CLAIM_TEXT"
        assert parsed["valueType"] == "ST"
        # Deserialize back
        obs2 = Observation.model_validate_json(json_str)
        assert obs2.run_id == obs.run_id
        assert obs2.code == obs.code

    def test_valid_nm_observation(self):
        obs = Observation(
            **_make_obs(
                agent="claim-detector",
                code="CHECK_WORTHY_SCORE",
                value="0.84",
                valueType="NM",
                units="score",
                referenceRange="0.0-1.0",
            )
        )
        assert obs.value == "0.84"

    def test_valid_cwe_observation(self):
        obs = Observation(
            **_make_obs(
                agent="claimreview-matcher",
                code="CLAIMREVIEW_MATCH",
                value="TRUE^Match Found^FCK",
                valueType="CWE",
            )
        )
        assert obs.value_type == ValueType.CWE

    def test_valid_tx_observation(self):
        long_text = "A" * 201
        obs = Observation(
            **_make_obs(
                agent="synthesizer",
                code="VERDICT_NARRATIVE",
                value=long_text,
                valueType="TX",
            )
        )
        assert obs.value_type == ValueType.TX

    def test_value_type_mismatch_rejected(self):
        with pytest.raises(ValidationError, match="requires valueType NM"):
            Observation(
                **_make_obs(
                    agent="synthesizer",
                    code="CONFIDENCE_SCORE",
                    value="0.84",
                    valueType="ST",
                )
            )

    def test_nm_non_numeric_rejected(self):
        with pytest.raises(ValidationError, match="parseable as float"):
            Observation(
                **_make_obs(
                    agent="claim-detector",
                    code="CHECK_WORTHY_SCORE",
                    value="not-a-number",
                    valueType="NM",
                    units="score",
                )
            )

    def test_cwe_bad_format_rejected(self):
        with pytest.raises(ValidationError, match="CODE\\^Display\\^System"):
            Observation(
                **_make_obs(
                    agent="claimreview-matcher",
                    code="CLAIMREVIEW_MATCH",
                    value="just a string",
                    valueType="CWE",
                )
            )

    def test_tx_short_value_rejected(self):
        with pytest.raises(ValidationError, match="exceed 200"):
            Observation(
                **_make_obs(
                    agent="synthesizer",
                    code="VERDICT_NARRATIVE",
                    value="too short",
                    valueType="TX",
                )
            )

    def test_seq_zero_rejected(self):
        with pytest.raises(ValidationError):
            Observation(**_make_obs(seq=0))

    def test_seq_negative_rejected(self):
        with pytest.raises(ValidationError):
            Observation(**_make_obs(seq=-1))

    def test_invalid_status_rejected(self):
        with pytest.raises(ValidationError, match="Invalid epistemic status"):
            Observation(**_make_obs(status="Z"))

    def test_note_max_length(self):
        with pytest.raises(ValidationError):
            Observation(**_make_obs(note="A" * 513))

    def test_note_within_limit(self):
        obs = Observation(**_make_obs(note="A" * 512))
        assert len(obs.note) == 512


# ── Stream messages ───────────────────────────────────────────────────


class TestStartMessage:
    def test_construction(self):
        msg = StartMessage(
            runId="test-run-001",
            agent="coverage-left",
            phase="fanout",
            timestamp="2026-04-06T12:00:01Z",
        )
        assert msg.type == "START"
        assert msg.phase == Phase.FANOUT

    def test_invalid_phase_rejected(self):
        with pytest.raises(ValidationError):
            StartMessage(
                runId="test-run-001",
                agent="coverage-left",
                phase="invalid",
                timestamp="2026-04-06T12:00:01Z",
            )


class TestStopMessage:
    def test_construction(self):
        msg = StopMessage(
            runId="test-run-001",
            agent="coverage-left",
            finalStatus="F",
            observationCount=12,
            timestamp="2026-04-06T12:00:08Z",
        )
        assert msg.type == "STOP"
        assert msg.final_status == "F"

    def test_invalid_final_status_rejected(self):
        with pytest.raises(ValidationError):
            StopMessage(
                runId="test-run-001",
                agent="coverage-left",
                finalStatus="P",
                observationCount=12,
                timestamp="2026-04-06T12:00:08Z",
            )


class TestStreamMessageUnion:
    def test_discriminated_start(self):
        adapter = TypeAdapter(StreamMessage)
        msg = adapter.validate_python(
            {
                "type": "START",
                "runId": "run-001",
                "agent": "coverage-left",
                "phase": "fanout",
                "timestamp": "2026-04-06T12:00:01Z",
            }
        )
        assert isinstance(msg, StartMessage)

    def test_discriminated_obs(self):
        adapter = TypeAdapter(StreamMessage)
        msg = adapter.validate_python(
            {
                "type": "OBS",
                "observation": _make_obs(),
            }
        )
        assert isinstance(msg, ObsMessage)
        assert isinstance(msg.observation, Observation)

    def test_discriminated_stop(self):
        adapter = TypeAdapter(StreamMessage)
        msg = adapter.validate_python(
            {
                "type": "STOP",
                "runId": "run-001",
                "agent": "coverage-left",
                "finalStatus": "F",
                "observationCount": 5,
                "timestamp": "2026-04-06T12:00:08Z",
            }
        )
        assert isinstance(msg, StopMessage)

    def test_json_round_trip(self):
        adapter = TypeAdapter(StreamMessage)
        original = StartMessage(
            runId="run-001",
            agent="agent-a",
            phase="ingestion",
            timestamp="2026-04-06T12:00:00Z",
        )
        json_bytes = adapter.dump_json(original, by_alias=True)
        restored = adapter.validate_json(json_bytes)
        assert isinstance(restored, StartMessage)
        assert restored.run_id == "run-001"
