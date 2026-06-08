from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Protocol, Sequence

from src.action.car_functions import run_tool
from src.memory.clarification_learner import ClarificationLearner
from src.memory.preference_table import PreferenceRecord, PreferenceTable
from src.policy.policy import Decision, Policy


class MemoryStoreLike(Protocol):
    def add(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        force_segment: bool = False,
        force_extract: bool = False,
    ) -> dict[str, Any]:
        ...

    def retrieve(self, query: str, limit: int = 5) -> list[str]:
        ...


@dataclass(frozen=True)
class PendingClarification:
    original_context: str
    question: str
    retrieval_hits: list[str]
    retrieved_prefs: list[dict[str, Any]]


@dataclass(frozen=True)
class TurnResult:
    status: str
    assistant_text: str
    decision: Decision
    tool_result: dict[str, Any] | None = None
    retrieval_hits: list[str] = field(default_factory=list)
    retrieved_prefs: list[dict[str, Any]] = field(default_factory=list)
    pending: PendingClarification | None = None
    learned_preference: PreferenceRecord | None = None
    expired_preferences: list[PreferenceRecord] = field(default_factory=list)


class DemoSession:
    def __init__(
        self,
        *,
        policy: Policy,
        memory_store: MemoryStoreLike,
        preference_table: PreferenceTable,
        learner: ClarificationLearner,
        retrieve_limit: int = 5,
    ) -> None:
        self.policy = policy
        self.memory_store = memory_store
        self.preference_table = preference_table
        self.learner = learner
        self.retrieve_limit = retrieve_limit
        self.session_messages: list[dict[str, str]] = []

    def handle_user_message(self, text: str) -> TurnResult:
        user_message = {"role": "user", "content": text, "time_stamp": _now()}
        self.session_messages.append(user_message)
        self.memory_store.add([user_message])
        retrieval_hits, prefs = self._retrieve_preferences(text)
        decision = self.policy.decide(context=text, retrieved_prefs=prefs)
        return self._materialize_decision(
            decision=decision,
            context=text,
            retrieval_hits=retrieval_hits,
            prefs=prefs,
        )

    def handle_clarification(
        self,
        pending: PendingClarification,
        answer: str,
    ) -> TurnResult:
        answer_message = {"role": "user", "content": answer, "time_stamp": _now()}
        self.session_messages.append(answer_message)
        self.memory_store.add([answer_message])
        combined_context = (
            f"用户先说：{pending.original_context}\n"
            f"系统追问：{pending.question}\n"
            f"用户回答：{answer}"
        )
        retrieval_hits, prefs = self._retrieve_preferences(combined_context)
        decision = self.policy.decide(context=combined_context, retrieved_prefs=prefs)
        result = self._materialize_decision(
            decision=decision,
            context=combined_context,
            retrieval_hits=retrieval_hits,
            prefs=prefs,
        )
        if result.status == "acted":
            learned = self.learner.learn_from_dialogue(
                context=pending.original_context,
                question=pending.question,
                answer=answer,
                tool_name=decision.tool_name,
                tool_args=decision.tool_args,
                retrieved_prefs=pending.retrieved_prefs,
            )
            expired = self.learner.reconcile_learned_preference(learned)
            return TurnResult(
                status=result.status,
                assistant_text=result.assistant_text,
                decision=result.decision,
                tool_result=result.tool_result,
                retrieval_hits=result.retrieval_hits,
                retrieved_prefs=result.retrieved_prefs,
                pending=result.pending,
                learned_preference=learned,
                expired_preferences=expired,
            )
        return result

    def remember_preference(
        self,
        *,
        preference: str,
        value: Any,
        condition: Mapping[str, Any],
        source: str,
        evidence: str,
    ) -> PreferenceRecord:
        from src.memory.preference_table import Condition

        record = self.preference_table.add_preference(
            preference=preference,
            value=value,
            condition=Condition.from_dict(dict(condition)),
            source=source,
            evidence=evidence,
            lightmem_ref=evidence,
        )
        memory_message = {"role": "user", "content": evidence, "time_stamp": _now()}
        self.session_messages.append(memory_message)
        self.memory_store.add(
            [memory_message],
            force_segment=True,
            force_extract=True,
        )
        return record

    def _retrieve_preferences(self, context: str) -> tuple[list[str], list[dict[str, Any]]]:
        retrieval_hits = self.memory_store.retrieve(context, limit=self.retrieve_limit)
        prefs = [
            record.to_policy_payload()
            for record in self.preference_table.find_relevant(
                query_text=context,
                lightmem_hits=retrieval_hits,
                limit=self.retrieve_limit,
            )
        ]
        return retrieval_hits, prefs

    def _materialize_decision(
        self,
        *,
        decision: Decision,
        context: str,
        retrieval_hits: list[str],
        prefs: list[dict[str, Any]],
    ) -> TurnResult:
        tool_result = run_tool(decision.tool_name, decision.tool_args)
        if decision.action == "ASK":
            question = decision.question or tool_result.get("question", "")
            assistant_message = {
                "role": "assistant",
                "content": question,
                "time_stamp": _now(),
            }
            self.session_messages.append(assistant_message)
            return TurnResult(
                status="needs_user_input",
                assistant_text=question,
                decision=decision,
                tool_result=tool_result,
                retrieval_hits=retrieval_hits,
                retrieved_prefs=prefs,
                pending=PendingClarification(
                    original_context=context,
                    question=question,
                    retrieval_hits=retrieval_hits,
                    retrieved_prefs=prefs,
                ),
            )
        return TurnResult(
            status="acted",
            assistant_text=tool_result["message"],
            decision=decision,
            tool_result=tool_result,
            retrieval_hits=retrieval_hits,
            retrieved_prefs=prefs,
        )


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
