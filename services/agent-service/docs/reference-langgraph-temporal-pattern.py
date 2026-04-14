# patient_intake.py
# Reference implementation showing clean LangGraph + Temporal separation.
# Source: provided by project lead as the target pattern.
#
# KEY PATTERNS:
# 1. LangGraph owns REASONING — extract, validate, route, decide
# 2. Temporal owns DURABILITY — retry, persist, signal, distribute
# 3. The entire LangGraph agent runs inside ONE Temporal activity
# 4. Temporal activities wrap side-effectful steps (EHR write, Slack notify)
# 5. No extra base classes or abstraction layers between them

import asyncio
import json
import re
from datetime import timedelta
from typing import TypedDict, Literal

# --- LangGraph ---
from langgraph.graph import StateGraph, END

# --- Temporal ---
from temporalio import workflow, activity
from temporalio.client import Client
from temporalio.worker import Worker

# --- Anthropic (LLM) ---
import anthropic

# --- Fake FHIR / Slack clients (swap for real ones) ---
class FakeFHIRClient:
    def validate(self, data: dict) -> list[str]:
        errors = []
        if not data.get("given_name"):
            errors.append("Missing given_name")
        if not data.get("family_name"):
            errors.append("Missing family_name")
        if not data.get("dob"):
            errors.append("Missing dob")
        return errors

    def create_patient(self, data: dict) -> str:
        print(f"[FHIR] Creating patient: {data}")
        return "fhir-patient-id-abc123"

class FakeSlackClient:
    def post(self, message: str) -> None:
        print(f"[Slack] {message}")

fhir_client = FakeFHIRClient()
slack_client = FakeSlackClient()
anthropic_client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env


# =============================================================================
# LANGGRAPH LAYER
# Agent state, nodes, and graph compilation all live here.
# This is purely about reasoning — no durability concerns.
# =============================================================================

class IntakeState(TypedDict):
    messages: list[dict]      # raw SMS conversation history
    extracted: dict           # structured data pulled out by LLM
    confidence: float         # LLM self-reported confidence 0.0-1.0
    fhir_errors: list[str]    # validation errors from FHIR client
    needs_review: bool        # whether a human needs to sign off


def extract_node(state: IntakeState) -> IntakeState:
    conversation_text = "\n".join(
        f"{m['role'].upper()}: {m['content']}" for m in state["messages"]
    )

    prompt = f"""
You are a clinical data extraction assistant. Given the following SMS conversation
between a patient and an intake bot, extract structured patient information.

Conversation:
{conversation_text}

Respond ONLY with a JSON object in this exact format:
{{
  "data": {{
    "given_name": "...",
    "family_name": "...",
    "dob": "YYYY-MM-DD",
    "phone": "...",
    "chief_complaint": "...",
    "insurance_id": "..."
  }},
  "confidence": 0.0
}}

Set confidence between 0.0 and 1.0 based on how complete and unambiguous the
information is. Use null for any field that wasn't mentioned.
"""

    response = anthropic_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    parsed = json.loads(raw)

    return {
        **state,
        "extracted": parsed["data"],
        "confidence": float(parsed["confidence"]),
    }


def validate_node(state: IntakeState) -> IntakeState:
    errors = fhir_client.validate(state["extracted"])
    return {**state, "fhir_errors": errors}


def review_router(state: IntakeState) -> Literal["needs_review", "submit"]:
    if state["confidence"] < 0.85 or len(state["fhir_errors"]) > 0:
        return "needs_review"
    return "submit"


def flag_review_node(state: IntakeState) -> IntakeState:
    print(f"[LangGraph] Flagging for review. Confidence: {state['confidence']}, "
          f"FHIR errors: {state['fhir_errors']}")
    return {**state, "needs_review": True}


def submit_node(state: IntakeState) -> IntakeState:
    print(f"[LangGraph] Auto-submitting. Confidence: {state['confidence']}")
    fhir_client.create_patient(state["extracted"])
    return {**state, "needs_review": False}


# Wire the graph
_builder = StateGraph(IntakeState)
_builder.add_node("extract", extract_node)
_builder.add_node("validate", validate_node)
_builder.add_node("flag_review", flag_review_node)
_builder.add_node("submit", submit_node)

_builder.set_entry_point("extract")
_builder.add_edge("extract", "validate")
_builder.add_conditional_edges("validate", review_router)
_builder.add_edge("flag_review", END)
_builder.add_edge("submit", END)

intake_agent = _builder.compile()


# =============================================================================
# TEMPORAL LAYER
# Activities wrap side-effectful steps. The Workflow orchestrates them durably.
# This is purely about reliability — no reasoning logic lives here.
# =============================================================================

@activity.defn
async def run_intake_agent_activity(messages: list[dict]) -> dict:
    initial_state: IntakeState = {
        "messages": messages,
        "extracted": {},
        "confidence": 0.0,
        "fhir_errors": [],
        "needs_review": False,
    }
    result = intake_agent.invoke(initial_state)
    return dict(result)


@activity.defn
async def notify_reviewer_activity(patient_id: str, extracted: dict, fhir_errors: list[str]) -> None:
    error_summary = ", ".join(fhir_errors) if fhir_errors else "low confidence"
    slack_client.post(
        f":warning: Manual review needed for intake `{patient_id}`.\n"
        f"Reason: {error_summary}\n"
        f"Patient: {extracted.get('given_name')} {extracted.get('family_name')}\n"
        f"Signal approval: `temporal signal --workflow-id intake-{patient_id} "
        f"--name approve_review --input 'true'`"
    )


@activity.defn
async def submit_to_ehr_activity(extracted: dict) -> str:
    fhir_id = fhir_client.create_patient(extracted)
    return fhir_id


@workflow.defn
class PatientIntakeWorkflow:
    def __init__(self):
        self._review_decision: bool | None = None

    @workflow.run
    async def run(self, patient_id: str, messages: list[dict]) -> str:
        result = await workflow.execute_activity(
            run_intake_agent_activity,
            messages,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        if not result["needs_review"]:
            fhir_id = await workflow.execute_activity(
                submit_to_ehr_activity,
                result["extracted"],
                start_to_close_timeout=timedelta(minutes=2),
            )
            return f"Auto-submitted. FHIR ID: {fhir_id}"

        await workflow.execute_activity(
            notify_reviewer_activity,
            args=[patient_id, result["extracted"], result["fhir_errors"]],
            start_to_close_timeout=timedelta(minutes=1),
        )

        await workflow.wait_condition(
            lambda: self._review_decision is not None,
            timeout=timedelta(days=2),
        )

        if not self._review_decision:
            return f"Intake {patient_id} rejected by reviewer."

        fhir_id = await workflow.execute_activity(
            submit_to_ehr_activity,
            result["extracted"],
            start_to_close_timeout=timedelta(minutes=2),
        )
        return f"Reviewer approved. FHIR ID: {fhir_id}"

    @workflow.signal
    def approve_review(self, approved: bool) -> None:
        self._review_decision = approved
