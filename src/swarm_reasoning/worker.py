"""Temporal worker entrypoint: registers workflow and activities.

Listens on the agent-task-queue and dispatches ClaimVerificationWorkflow
and its associated activities.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal

from temporalio.client import Client
from temporalio.worker import Worker

from swarm_reasoning.activities.completion import rebuild_completion_register
from swarm_reasoning.activities.run_agent import run_agent_activity
from swarm_reasoning.activities.run_status import (
    cancel_run,
    fail_run,
    get_run_status,
    update_run_status,
)
from swarm_reasoning.workflows.claim_verification import ClaimVerificationWorkflow

TASK_QUEUE = "agent-task-queue"

logger = logging.getLogger(__name__)


async def run_worker() -> None:
    """Start the Temporal worker with all workflows and activities registered."""
    temporal_host = os.environ.get("TEMPORAL_HOST", "localhost:7233")
    temporal_namespace = os.environ.get("TEMPORAL_NAMESPACE", "default")

    logger.info("Connecting to Temporal at %s (namespace: %s)", temporal_host, temporal_namespace)
    client = await Client.connect(temporal_host, namespace=temporal_namespace)

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[ClaimVerificationWorkflow],
        activities=[
            run_agent_activity,
            update_run_status,
            cancel_run,
            fail_run,
            get_run_status,
            rebuild_completion_register,
        ],
    )

    # Graceful shutdown on SIGTERM
    shutdown_event = asyncio.Event()

    def _handle_signal() -> None:
        logger.info("Received shutdown signal, stopping worker...")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal)

    logger.info("Worker started, listening on queue: %s", TASK_QUEUE)

    # Run worker until shutdown signal
    async with worker:
        await shutdown_event.wait()

    logger.info("Worker shut down gracefully")


def main() -> None:
    """CLI entrypoint."""
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
