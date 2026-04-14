"""Observation resolution: C > F precedence, X and P excluded (ADR-003, ADR-005)."""

from __future__ import annotations

import logging

from swarm_reasoning.agents.synthesizer.models import ResolvedObservation, ResolvedObservationSet
from swarm_reasoning.stream.base import ReasoningStream
from swarm_reasoning.stream.key import stream_key

logger = logging.getLogger(__name__)

# All 9 upstream agent names the synthesizer reads from.
UPSTREAM_AGENTS = [
    "ingestion-agent",
    "claim-detector",
    "entity-extractor",
    "claimreview-matcher",
    "coverage-left",
    "coverage-center",
    "coverage-right",
    "domain-evidence",
    "validation",
]


class ObservationResolver:
    """Resolve upstream observations using epistemic status precedence."""

    async def resolve(self, run_id: str, stream: ReasoningStream) -> ResolvedObservationSet:
        """Read all 10 upstream agent streams and apply resolution algorithm.

        For each (agent, code) pair:
        1. If any C-status, use highest seq C -> resolution_method="LATEST_C"
        2. Else if any F-status, use highest seq F -> resolution_method="LATEST_F"
        3. X-status excluded silently, P-status excluded with warning.
        """
        # Collect all OBX observations keyed by (agent, code)
        pair_observations: dict[tuple[str, str], list[dict]] = {}
        excluded: list[dict] = []
        warnings: list[str] = []

        for agent_name in UPSTREAM_AGENTS:
            sk = stream_key(run_id, agent_name)
            try:
                messages = await stream.read_range(sk)
            except Exception:
                logger.warning("Failed to read stream %s", sk)
                continue

            for msg in messages:
                if msg.type != "OBS":
                    continue
                obs = msg.observation
                key = (obs.agent, obs.code.value if hasattr(obs.code, "value") else obs.code)
                if key not in pair_observations:
                    pair_observations[key] = []
                pair_observations[key].append(
                    {
                        "agent": obs.agent,
                        "code": obs.code.value if hasattr(obs.code, "value") else obs.code,
                        "value": obs.value,
                        "value_type": (
                            obs.value_type.value
                            if hasattr(obs.value_type, "value")
                            else obs.value_type
                        ),
                        "seq": obs.seq,
                        "status": obs.status,
                        "timestamp": obs.timestamp,
                        "method": obs.method,
                        "note": obs.note,
                        "units": obs.units,
                        "reference_range": obs.reference_range,
                    }
                )

        # Apply resolution per (agent, code) pair
        resolved: list[ResolvedObservation] = []

        for (agent_name, code), obs_list in pair_observations.items():
            c_status = [o for o in obs_list if o["status"] == "C"]
            f_status = [o for o in obs_list if o["status"] == "F"]
            x_status = [o for o in obs_list if o["status"] == "X"]
            p_status = [o for o in obs_list if o["status"] == "P"]

            if c_status:
                # Use highest seq C observation
                winner = max(c_status, key=lambda o: o["seq"])
                resolved.append(
                    ResolvedObservation(
                        agent=winner["agent"],
                        code=winner["code"],
                        value=winner["value"],
                        value_type=winner["value_type"],
                        seq=winner["seq"],
                        status=winner["status"],
                        resolution_method="LATEST_C",
                        timestamp=winner["timestamp"],
                        method=winner["method"],
                        note=winner["note"],
                        units=winner["units"],
                        reference_range=winner["reference_range"],
                    )
                )
            elif f_status:
                # Use highest seq F observation
                winner = max(f_status, key=lambda o: o["seq"])
                resolved.append(
                    ResolvedObservation(
                        agent=winner["agent"],
                        code=winner["code"],
                        value=winner["value"],
                        value_type=winner["value_type"],
                        seq=winner["seq"],
                        status=winner["status"],
                        resolution_method="LATEST_F",
                        timestamp=winner["timestamp"],
                        method=winner["method"],
                        note=winner["note"],
                        units=winner["units"],
                        reference_range=winner["reference_range"],
                    )
                )
            else:
                # Only X and/or P status observations
                for o in x_status:
                    excluded.append(o)
                for o in p_status:
                    excluded.append(o)
                    warnings.append(
                        f"WARNING: {agent_name}:{code} has only P-status observations; "
                        "upstream agent may not have finalized."
                    )

        return ResolvedObservationSet(
            observations=resolved,
            synthesis_signal_count=len(resolved),
            excluded_observations=excluded,
            warnings=warnings,
        )
