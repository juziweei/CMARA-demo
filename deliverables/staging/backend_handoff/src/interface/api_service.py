from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
from uuid import uuid4

from src.demo_scenarios import (
    get_demo_scenario,
    list_demo_scenarios,
    seed_scenario_preferences,
)
from src.interface.runtime import RuntimeBundle, build_runtime, reset_demo_state
from src.interface.session import PendingClarification, TurnResult
from src.memory.lightmem_store import MemoryHit

DEFAULT_SESSION_ID = "default"


class APIServiceError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class SessionState:
    runtime: RuntimeBundle
    pending_by_id: dict[str, PendingClarification] = field(default_factory=dict)
    active_scenario_id: str | None = None
    active_scenario_step: int = 0
    active_scenario_name: str = ""
    active_scenario_script: list[dict[str, Any]] = field(default_factory=list)


class DemoAPIService:
    def __init__(
        self,
        *,
        runtime_factory: Callable[[], RuntimeBundle] | None = None,
        reset_callback: Callable[[], None] | None = None,
    ) -> None:
        self._runtime_factory = runtime_factory or build_runtime
        self._reset_callback = reset_callback or reset_demo_state
        self._state = SessionState(runtime=self._runtime_factory())

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "session_id": DEFAULT_SESSION_ID,
            "active_scenario_id": self._state.active_scenario_id,
            "memory_mode": self._state.runtime.memory_mode,
        }

    def scenarios(self) -> dict[str, Any]:
        return {
            "session_id": DEFAULT_SESSION_ID,
            "scenarios": list_demo_scenarios(),
            "active_scenario_id": self._state.active_scenario_id,
            "active_step": self._state.active_scenario_step,
        }

    def scenario(self, *, scenario_id: str, session_id: str | None = None) -> dict[str, Any]:
        self._require_session(session_id)
        try:
            scenario = get_demo_scenario(scenario_id)
        except KeyError as exc:
            raise APIServiceError(str(exc), status_code=404) from exc
        return {
            "session_id": DEFAULT_SESSION_ID,
            "scenario": scenario,
        }

    def turn(self, *, text: str, session_id: str | None = None) -> dict[str, Any]:
        self._require_session(session_id)
        normalized = str(text or "").strip()
        if not normalized:
            raise APIServiceError("text must not be empty")
        result = self._state.runtime.session.handle_user_message(normalized)
        return self._serialize_turn_result(result)

    def clarification(
        self,
        *,
        answer: str,
        pending_id: str,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        self._require_session(session_id)
        normalized_answer = str(answer or "").strip()
        if not normalized_answer:
            raise APIServiceError("answer must not be empty")
        pending_key = str(pending_id or "").strip()
        if not pending_key:
            raise APIServiceError("pending_id must not be empty")
        pending = self._state.pending_by_id.pop(pending_key, None)
        if pending is None:
            raise APIServiceError(
                f"pending clarification not found: {pending_key}",
                status_code=404,
            )
        result = self._state.runtime.session.handle_clarification(
            pending,
            normalized_answer,
        )
        return self._serialize_turn_result(result)

    def summarize(self, *, session_id: str | None = None) -> dict[str, Any]:
        self._require_session(session_id)
        additions = self._state.runtime.summarizer.summarize(
            self._state.runtime.session.session_messages
        )
        return {
            "session_id": DEFAULT_SESSION_ID,
            "added_preferences": [record.to_dict() for record in additions],
            "count": len(additions),
        }

    def preferences(self, *, session_id: str | None = None) -> dict[str, Any]:
        self._require_session(session_id)
        records = self._state.runtime.preference_table.list_preferences()
        return {
            "session_id": DEFAULT_SESSION_ID,
            "preferences": [record.to_dict() for record in records],
            "count": len(records),
        }

    def reset(self, *, session_id: str | None = None) -> dict[str, Any]:
        self._require_session(session_id)
        self._reset_callback()
        self._state = SessionState(runtime=self._runtime_factory())
        return {"session_id": DEFAULT_SESSION_ID, "status": "reset"}

    def seed_family_trip_demo(
        self,
        *,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        return self.run_scenario(scenario_id="family_trip", session_id=session_id)

    def run_scenario(
        self,
        *,
        scenario_id: str,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        self._require_session(session_id)
        try:
            scenario = get_demo_scenario(scenario_id)
        except KeyError as exc:
            raise APIServiceError(str(exc), status_code=404) from exc
        self._reset_callback()
        self._state = SessionState(runtime=self._runtime_factory())
        session = self._state.runtime.session
        seed_scenario_preferences(session, scenario_id)
        self._state.active_scenario_id = scenario["id"]
        self._state.active_scenario_step = 0
        self._state.active_scenario_name = scenario.get("title", "")
        self._state.active_scenario_script = list(scenario.get("script", []))
        return self._advance_active_scenario()

    def advance_active_scenario(
        self,
        *,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        self._require_session(session_id)
        return self._advance_active_scenario()

    def _advance_active_scenario(self) -> dict[str, Any]:
        if not self._state.active_scenario_script:
            raise APIServiceError("no active scenario is running")
        if self._state.active_scenario_step >= len(self._state.active_scenario_script):
            return {
                "session_id": DEFAULT_SESSION_ID,
                "status": "completed",
                "scenario_id": self._state.active_scenario_id,
                "step_index": self._state.active_scenario_step,
                "step": None,
                "result": None,
            }

        step = self._state.active_scenario_script[self._state.active_scenario_step]
        self._state.active_scenario_step += 1
        kind = str(step.get("kind", "turn"))
        label = str(step.get("label", ""))
        text = str(step.get("text", ""))
        if kind == "summary":
            result = self.summarize()
        elif kind == "clarification":
            pending = self._latest_pending()
            if pending is None:
                result = {
                    "session_id": DEFAULT_SESSION_ID,
                    "status": "skipped",
                    "reason": "no pending clarification",
                }
            else:
                result = self.clarification(
                    answer=text,
                    pending_id=pending,
                )
        else:
            result = self.turn(text=text)
        return {
            "session_id": DEFAULT_SESSION_ID,
            "status": "advanced",
            "scenario_id": self._state.active_scenario_id,
            "scenario_name": self._state.active_scenario_name,
            "step_index": self._state.active_scenario_step,
            "step": {
                "kind": kind,
                "label": label,
                "text": text,
            },
            "result": result,
        }

    def _latest_pending(self) -> str | None:
        if not self._state.pending_by_id:
            return None
        return next(reversed(self._state.pending_by_id))

    def _serialize_turn_result(self, result: TurnResult) -> dict[str, Any]:
        pending_payload: dict[str, Any] | None = None
        if result.pending is not None:
            pending_id = uuid4().hex
            self._state.pending_by_id[pending_id] = result.pending
            pending_payload = {
                "pending_id": pending_id,
                "question": result.pending.question,
                "original_context": result.pending.original_context,
            }

        return {
            "session_id": DEFAULT_SESSION_ID,
            "status": result.status,
            "assistant_text": result.assistant_text,
            "decision": {
                "action": result.decision.action,
                "tool_name": result.decision.tool_name,
                "tool_args": dict(result.decision.tool_args),
                "question": result.decision.question,
                "rationale": result.decision.rationale,
            },
            "tool_result": result.tool_result,
            "retrieval_hits": [_serialize_hit(hit) for hit in result.retrieval_hits],
            "retrieved_preferences": list(result.retrieved_prefs),
            "pending": pending_payload,
            "learned_preference": (
                result.learned_preference.to_dict()
                if result.learned_preference is not None
                else None
            ),
            "expired_preferences": [
                record.to_dict() for record in result.expired_preferences
            ],
            "decision_trace": result.decision_trace,
        }

    def _require_session(self, session_id: str | None) -> None:
        normalized = str(session_id or DEFAULT_SESSION_ID).strip() or DEFAULT_SESSION_ID
        if normalized != DEFAULT_SESSION_ID:
            raise APIServiceError(
                "this demo API currently supports only session_id='default'"
            )

def _serialize_hit(hit: MemoryHit) -> dict[str, Any]:
    return {
        "id": hit.id,
        "memory": hit.memory,
        "time_stamp": hit.time_stamp,
        "speaker_name": hit.speaker_name,
        "score": hit.score,
        "payload": dict(hit.payload),
    }
