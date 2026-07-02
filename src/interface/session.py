from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Protocol, Sequence

from src.action.assistant_responder import AssistantResponder
from src.action.car_functions import run_tool
from src.memory.clarification_learner import ClarificationLearner
from src.memory.lightmem_store import MemoryHit
from src.memory.preference_table import PreferenceRecord, PreferenceTable
from src.policy.policy import Decision, Policy, PreparedPolicyInput


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

    def retrieve_records(self, query: str, limit: int = 5) -> list[MemoryHit]:
        ...


@dataclass(frozen=True)
class PendingClarification:
    original_context: str
    question: str
    retrieval_hits: list[MemoryHit]
    retrieved_prefs: list[dict[str, Any]]


@dataclass(frozen=True)
class TurnResult:
    status: str
    assistant_text: str
    decision: Decision
    tool_result: dict[str, Any] | None = None
    retrieval_hits: list[MemoryHit] = field(default_factory=list)
    retrieved_prefs: list[dict[str, Any]] = field(default_factory=list)
    pending: PendingClarification | None = None
    learned_preference: PreferenceRecord | None = None
    expired_preferences: list[PreferenceRecord] = field(default_factory=list)
    decision_trace: dict[str, Any] = field(default_factory=dict)


class DemoSession:
    def __init__(
        self,
        *,
        policy: Policy,
        memory_store: MemoryStoreLike,
        preference_table: PreferenceTable,
        learner: ClarificationLearner,
        responder: AssistantResponder | None = None,
        retrieve_limit: int = 5,
    ) -> None:
        self.policy = policy
        self.memory_store = memory_store
        self.preference_table = preference_table
        self.learner = learner
        self.responder = responder
        self.retrieve_limit = retrieve_limit
        self.session_messages: list[dict[str, str]] = []

    def handle_user_message(self, text: str) -> TurnResult:
        user_message = {"role": "user", "content": text, "time_stamp": _now()}
        self.session_messages.append(user_message)
        memory_inputs = [user_message]
        retrieval_hits, prefs = self._retrieve_preferences(text)
        if self._should_reply_normally(text=text, prefs=prefs):
            return self._reply_normally(
                context=text,
                retrieval_hits=retrieval_hits,
                prefs=prefs,
                memory_inputs=memory_inputs,
            )
        prepared = self.policy.prepare_inputs(context=text, retrieved_prefs=prefs)
        decision = self.policy.decide_prepared(context=text, prepared=prepared)
        return self._materialize_decision(
            decision=decision,
            context=text,
            retrieval_hits=retrieval_hits,
            prefs=prefs,
            prepared=prepared,
            memory_inputs=memory_inputs,
        )

    def handle_clarification(
        self,
        pending: PendingClarification,
        answer: str,
    ) -> TurnResult:
        answer_message = {"role": "user", "content": answer, "time_stamp": _now()}
        self.session_messages.append(answer_message)
        combined_context = (
            f"Original user request: {pending.original_context}\n"
            f"System clarification question: {pending.question}\n"
            f"User clarification answer: {answer}"
        )
        memory_inputs = [answer_message]
        retrieval_hits, prefs = self._retrieve_preferences(combined_context)
        prepared = self.policy.prepare_inputs(
            context=combined_context,
            retrieved_prefs=prefs,
        )
        decision = self.policy.decide_prepared(
            context=combined_context,
            prepared=prepared,
        )
        result = self._materialize_decision(
            decision=decision,
            context=combined_context,
            retrieval_hits=retrieval_hits,
            prefs=prefs,
            prepared=prepared,
            memory_inputs=memory_inputs,
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
                decision_trace={
                    **result.decision_trace,
                    "learned_preference": learned.to_dict(),
                    "expired_preferences": [record.to_dict() for record in expired],
                },
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

        record, _ = self.preference_table.upsert_preference(
            preference=preference,
            value=value,
            condition=Condition.from_dict(dict(condition)),
            source=source,
            evidence=evidence,
            lightmem_ref=evidence,
        )
        memory_message = {"role": "user", "content": evidence, "time_stamp": _now()}
        assistant_message = {
            "role": "assistant",
            "content": f"Recorded preference: {preference}={value}",
            "time_stamp": _now(),
        }
        self.session_messages.append(memory_message)
        self.session_messages.append(assistant_message)
        self.memory_store.add(
            [memory_message, assistant_message],
            force_segment=True,
            force_extract=True,
        )
        return record

    def _retrieve_preferences(self, context: str) -> tuple[list[MemoryHit], list[dict[str, Any]]]:
        retrieval_hits = self.memory_store.retrieve_records(
            context, limit=self.retrieve_limit
        )
        prefs = [
            match.record.to_policy_payload(
                matched_by=match.matched_by,
                retrieval_score=match.retrieval_score,
                query_score=match.query_score,
            )
            for match in self.preference_table.find_relevant_matches(
                query_text=context,
                lightmem_hits=retrieval_hits,
                limit=self.retrieve_limit,
            )
        ]
        return retrieval_hits, prefs

    def _reply_normally(
        self,
        *,
        context: str,
        retrieval_hits: list[MemoryHit],
        prefs: list[dict[str, Any]],
        memory_inputs: list[dict[str, str]],
    ) -> TurnResult:
        assistant_text = (
            self.responder.respond(
                user_text=context,
                retrieved_prefs=prefs,
                session_messages=self.session_messages,
            )
            if self.responder is not None
            else "Sure, I am here."
        )
        decision = Decision(
            action="REPLY",
            tool_name="general_chat",
            rationale="General conversation is handled by the assistant responder.",
        )
        tool_result = {
            "tool": "general_chat",
            "status": "replied",
            "message": assistant_text,
            "llm_response": assistant_text,
        }
        assistant_message = {
            "role": "assistant",
            "content": assistant_text,
            "time_stamp": _now(),
        }
        self.session_messages.append(assistant_message)
        self.memory_store.add([*memory_inputs, assistant_message])
        return TurnResult(
            status="replied",
            assistant_text=assistant_text,
            decision=decision,
            tool_result=tool_result,
            retrieval_hits=retrieval_hits,
            retrieved_prefs=prefs,
            decision_trace={
                "context": context,
                "retrieval_hits": [_summarize_hit(hit) for hit in retrieval_hits],
                "retrieved_preferences": prefs,
                "decision": {
                    "action": decision.action,
                    "tool_name": decision.tool_name,
                    "tool_args": dict(decision.tool_args),
                    "question": decision.question,
                    "rationale": decision.rationale,
                },
                "tool_result": tool_result,
            },
        )

    def _should_reply_normally(
        self,
        *,
        text: str,
        prefs: Sequence[Mapping[str, Any]],
    ) -> bool:
        if self.responder is None:
            return False
        normalized = text.strip()
        if not normalized:
            return False
        lowered = normalized.lower()
        action_markers = (
            "调",
            "设置",
            "设为",
            "打开",
            "关闭",
            "开到",
            "切到",
            "播放",
            "放",
            "升高",
            "降低",
            "热一点",
            "冷一点",
            "座椅",
            "空调",
            "温度",
            "音乐",
            "风",
            "ac",
            "air conditioning",
            "air conditioner",
            "climate",
            "temperature",
            "hot",
            "cold",
            "seat",
            "seat heating",
            "music",
            "play",
            "turn on",
            "turn off",
            "set",
            "adjust",
        )
        general_question_markers = (
            "怎么",
            "为什么",
            "啥",
            "什么",
            "能不能",
            "可不可以",
            "是否",
            "天气",
            "聊聊",
            "无聊",
            "介绍",
            "解释",
            "how",
            "why",
            "what",
            "weather",
            "chat",
            "bored",
            "explain",
            "tell me",
        )
        if any(marker in lowered for marker in action_markers):
            return False
        if "？" in normalized or "?" in normalized:
            return any(marker in normalized for marker in general_question_markers)
        if any(marker in normalized for marker in ("谢谢", "你好", "早上好", "晚上好", "再见")):
            return True
        if any(marker in lowered for marker in ("thanks", "hello", "hi", "good morning", "good evening", "bye")):
            return True
        if any(marker in normalized for marker in ("聊聊", "无聊", "陪我")):
            return True
        if any(marker in lowered for marker in ("chat", "bored", "talk with me")):
            return True
        return not prefs and len(normalized) >= 4 and any(
            marker in normalized for marker in general_question_markers
        )

    def _materialize_decision(
        self,
        *,
        decision: Decision,
        context: str,
        retrieval_hits: list[MemoryHit],
        prefs: list[dict[str, Any]],
        prepared: PreparedPolicyInput,
        memory_inputs: list[dict[str, str]],
    ) -> TurnResult:
        if decision.tool_name == "general_chat" and self.responder is not None:
            return self._reply_normally(
                context=context,
                retrieval_hits=retrieval_hits,
                prefs=prefs,
                memory_inputs=memory_inputs,
            )
        tool_result = run_tool(decision.tool_name, decision.tool_args)
        assistant_text = tool_result["message"]
        result_status = "acted"
        decision_trace = {
            **prepared.trace,
            "retrieval_hits": [_summarize_hit(hit) for hit in retrieval_hits],
            "retrieved_preferences": prefs,
            "decision": {
                "action": decision.action,
                "tool_name": decision.tool_name,
                "tool_args": dict(decision.tool_args),
                "question": decision.question,
                "rationale": decision.rationale,
            },
            "tool_result": tool_result,
        }
        if decision.action == "ASK":
            question = decision.question or tool_result.get("question", "")
            assistant_message = {
                "role": "assistant",
                "content": question,
                "time_stamp": _now(),
            }
            self.session_messages.append(assistant_message)
            self.memory_store.add([*memory_inputs, assistant_message])
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
                decision_trace=decision_trace,
            )
        assistant_message = {
            "role": "assistant",
            "content": assistant_text,
            "time_stamp": _now(),
        }
        self.session_messages.append(assistant_message)
        self.memory_store.add([*memory_inputs, assistant_message])
        return TurnResult(
            status=result_status,
            assistant_text=assistant_text,
            decision=decision,
            tool_result=tool_result,
            retrieval_hits=retrieval_hits,
            retrieved_prefs=prefs,
            decision_trace=decision_trace,
        )


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _summarize_hit(hit: MemoryHit) -> dict[str, Any]:
    return {
        "id": hit.id,
        "memory": hit.memory,
        "time_stamp": hit.time_stamp,
        "speaker_name": hit.speaker_name,
        "score": hit.score,
    }
