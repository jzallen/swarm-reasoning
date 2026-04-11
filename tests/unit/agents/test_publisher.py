"""Unit tests for entity-extractor observation publisher."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from swarm_reasoning.agents.entity_extractor.extractor import EntityExtractionResult
from swarm_reasoning.agents.entity_extractor.publisher import (
    normalize_date,
    publish_entities,
    publish_error_stop,
)
from swarm_reasoning.models.observation import ObservationCode
from swarm_reasoning.models.stream import ObsMessage, StartMessage, StopMessage


class TestNormalizeDate:
    def test_yyyymmdd_passthrough(self):
        value, note = normalize_date("20210115")
        assert value == "20210115"
        assert note is None

    def test_range_passthrough(self):
        value, note = normalize_date("20210101-20211231")
        assert value == "20210101-20211231"
        assert note is None

    def test_year_only_expands_to_range(self):
        value, note = normalize_date("2021")
        assert value == "20210101-20211231"
        assert note is None

    def test_unparseable_returns_raw_with_note(self):
        value, note = normalize_date("last Tuesday")
        assert value == "last Tuesday"
        assert note == "date-not-normalized"

    def test_strips_whitespace(self):
        value, note = normalize_date("  20210115  ")
        assert value == "20210115"
        assert note is None


class TestPublishEntities:
    @pytest.mark.asyncio
    async def test_two_persons_one_org(self):
        stream = AsyncMock()
        stream.publish = AsyncMock()

        result = EntityExtractionResult(
            persons=["Alice", "Bob"],
            organizations=["Acme Corp"],
            dates=[],
            locations=[],
            statistics=[],
        )

        count = await publish_entities("run-001", result, stream)

        assert count == 3
        calls = stream.publish.call_args_list
        # START + 3 OBS + STOP = 5 calls
        assert len(calls) == 5

        # START
        start_msg = calls[0][0][1]
        assert isinstance(start_msg, StartMessage)
        assert start_msg.agent == "entity-extractor"

        # OBS 1: ENTITY_PERSON "Alice" seq=1
        obs1 = calls[1][0][1]
        assert isinstance(obs1, ObsMessage)
        assert obs1.observation.code == ObservationCode.ENTITY_PERSON
        assert obs1.observation.value == "Alice"
        assert obs1.observation.seq == 1
        assert obs1.observation.status == "F"

        # OBS 2: ENTITY_PERSON "Bob" seq=2
        obs2 = calls[2][0][1]
        assert obs2.observation.code == ObservationCode.ENTITY_PERSON
        assert obs2.observation.value == "Bob"
        assert obs2.observation.seq == 2

        # OBS 3: ENTITY_ORG "Acme Corp" seq=3
        obs3 = calls[3][0][1]
        assert obs3.observation.code == ObservationCode.ENTITY_ORG
        assert obs3.observation.value == "Acme Corp"
        assert obs3.observation.seq == 3

        # STOP
        stop_msg = calls[4][0][1]
        assert isinstance(stop_msg, StopMessage)
        assert stop_msg.final_status == "F"
        assert stop_msg.observation_count == 3

    @pytest.mark.asyncio
    async def test_empty_result_zero_obs(self):
        stream = AsyncMock()
        stream.publish = AsyncMock()

        result = EntityExtractionResult(
            persons=[], organizations=[], dates=[], locations=[], statistics=[]
        )

        count = await publish_entities("run-001", result, stream)

        assert count == 0
        calls = stream.publish.call_args_list
        # START + STOP only
        assert len(calls) == 2

        stop_msg = calls[1][0][1]
        assert isinstance(stop_msg, StopMessage)
        assert stop_msg.observation_count == 0

    @pytest.mark.asyncio
    async def test_date_normalization_applied(self):
        stream = AsyncMock()
        stream.publish = AsyncMock()

        result = EntityExtractionResult(
            persons=[],
            organizations=[],
            dates=["2021", "last Tuesday"],
            locations=[],
            statistics=[],
        )

        count = await publish_entities("run-001", result, stream)

        assert count == 2
        calls = stream.publish.call_args_list

        # OBS 1: "2021" -> "20210101-20211231", note=None
        obs1 = calls[1][0][1]
        assert obs1.observation.code == ObservationCode.ENTITY_DATE
        assert obs1.observation.value == "20210101-20211231"
        assert obs1.observation.note is None

        # OBS 2: "last Tuesday" -> "last Tuesday", note="date-not-normalized"
        obs2 = calls[2][0][1]
        assert obs2.observation.code == ObservationCode.ENTITY_DATE
        assert obs2.observation.value == "last Tuesday"
        assert obs2.observation.note == "date-not-normalized"

    @pytest.mark.asyncio
    async def test_deterministic_order(self):
        """Entities published in order: PERSON, ORG, DATE, LOCATION, STATISTIC."""
        stream = AsyncMock()
        stream.publish = AsyncMock()

        result = EntityExtractionResult(
            persons=["Alice"],
            organizations=["Acme"],
            dates=["20210101"],
            locations=["NYC"],
            statistics=["50%"],
        )

        await publish_entities("run-001", result, stream)

        calls = stream.publish.call_args_list
        # Skip START (index 0) and STOP (index -1)
        obs_calls = calls[1:-1]
        codes = [c[0][1].observation.code for c in obs_calls]
        assert codes == [
            ObservationCode.ENTITY_PERSON,
            ObservationCode.ENTITY_ORG,
            ObservationCode.ENTITY_DATE,
            ObservationCode.ENTITY_LOCATION,
            ObservationCode.ENTITY_STATISTIC,
        ]

        # Verify monotonic seq
        seqs = [c[0][1].observation.seq for c in obs_calls]
        assert seqs == [1, 2, 3, 4, 5]


class TestPublishErrorStop:
    @pytest.mark.asyncio
    async def test_error_stop_published(self):
        stream = AsyncMock()
        stream.publish = AsyncMock()

        await publish_error_stop("run-001", stream)

        calls = stream.publish.call_args_list
        assert len(calls) == 1
        stop_msg = calls[0][0][1]
        assert isinstance(stop_msg, StopMessage)
        assert stop_msg.final_status == "X"
        assert stop_msg.observation_count == 0
