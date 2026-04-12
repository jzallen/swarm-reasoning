"""Temporal worker entry point — runs all 11 agent workers + workflow worker.

Usage:
    python -m swarm_reasoning.temporal.worker

All workers run in a single Python process using asyncio. Each agent worker
polls its own task queue (agent:{agent-name}) with max_concurrent_activities=1
because agents are LLM-bound. The workflow worker polls the claim-verification
task queue.

Graceful shutdown: SIGTERM/SIGINT drains in-progress activities before exit.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

from temporalio.client import Client
from temporalio.worker import Worker

from swarm_reasoning.temporal.activities import (
    AGENT_NAMES,
    WORKFLOW_TASK_QUEUE,
    run_agent_activity,
    task_queue_for_agent,
)
from swarm_reasoning.temporal.config import TemporalConfig
from swarm_reasoning.temporal.workflow import ClaimVerificationWorkflow

logger = logging.getLogger(__name__)


async def create_workers(client: Client) -> list[Worker]:
    """Create all Temporal workers: 11 agent workers + 1 workflow worker."""
    workers: list[Worker] = []

    # One worker per agent type, each polling its own task queue
    for agent_name in AGENT_NAMES:
        worker = Worker(
            client,
            task_queue=task_queue_for_agent(agent_name),
            activities=[run_agent_activity],
            max_concurrent_activities=1,
        )
        workers.append(worker)

    # Workflow worker — runs the ClaimVerificationWorkflow itself
    workflow_worker = Worker(
        client,
        task_queue=WORKFLOW_TASK_QUEUE,
        workflows=[ClaimVerificationWorkflow],
    )
    workers.append(workflow_worker)

    return workers


async def run_workers(config: TemporalConfig | None = None) -> None:
    """Connect to Temporal and run all workers until shutdown."""
    cfg = config or TemporalConfig()

    logger.info("Connecting to Temporal at %s (namespace: %s)", cfg.address, cfg.namespace)

    try:
        client = await Client.connect(cfg.address, namespace=cfg.namespace)
    except Exception:
        logger.exception("Failed to connect to Temporal at %s", cfg.address)
        sys.exit(1)

    workers = await create_workers(client)
    logger.info("Starting %d workers (%d agents + 1 workflow)", len(workers), len(AGENT_NAMES))

    # Set up graceful shutdown on SIGTERM/SIGINT
    shutdown_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("Shutdown signal received, draining workers...")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _signal_handler)

    # Run all workers concurrently
    worker_tasks = [asyncio.create_task(w.run()) for w in workers]

    # Wait for shutdown signal
    await shutdown_event.wait()

    # Cancel all worker tasks (triggers graceful drain)
    for task in worker_tasks:
        task.cancel()

    # Wait for workers to finish draining
    await asyncio.gather(*worker_tasks, return_exceptions=True)
    logger.info("All workers shut down")


async def check_health(config: TemporalConfig | None = None) -> bool:
    """Check if the Temporal client connection is active."""
    cfg = config or TemporalConfig()
    try:
        client = await Client.connect(cfg.address, namespace=cfg.namespace)
        # A successful connection implies the server is reachable
        await client.service_client.check_health()
        return True
    except Exception:
        return False


def main() -> None:
    """CLI entry point for the worker process."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    asyncio.run(run_workers())


if __name__ == "__main__":
    main()
