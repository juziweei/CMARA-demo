from __future__ import annotations

import json
import re
from typing import Any
from typing import Mapping, Sequence

from src.action.llm_client import ToolChatClient
from src.memory.preference_table import (
    Condition,
    PreferenceRecord,
    PreferenceTable,
    infer_preference_from_text,
    normalize_preference_name,
)


class ClarificationLearner:
    SYSTEM_PROMPT = """
你在做车载长期记忆系统的澄清学习。
给你一次 ASK 的上下文、系统追问、用户回答、以及最后执行的动作。
你的任务是抽取“这次用户选择背后的关键条件”，并沉淀成一条可复用的长期偏好。

只输出 JSON，格式必须是：
{
  "preference": "...",
  "value": ...,
  "condition": {"type": "...", "operator": "==", "target": "..."} 或 {"type": "default"},
  "evidence": "..."
}

要求：
- condition 只保留真正区分选择的一两个关键维度，不要把整句回答原样塞进去。
- 如果系统问的是健康状态，就优先抽成 health_state 之类的条件。
- 如果上下文说明不舒服的是乘客、家人、妻子、后排成员，就优先抽成 passenger_health_state。
- health_state 的 target 统一规范成英文标签：sick / recovering / healthy。
- evidence 用一句话说明这条 learned preference 的依据。
""".strip()

    RETRY_SYSTEM_PROMPT = """
你是 JSON 修复器。请把上一次无效或不规范的澄清学习输出修复成合法 JSON。
不要写解释，不要写 markdown，只返回一个 JSON 对象。
""".strip()

    def __init__(
        self,
        preference_table: PreferenceTable,
        llm_client: ToolChatClient | None = None,
    ) -> None:
        self.preference_table = preference_table
        self.llm_client = llm_client

    def learn(
        self,
        *,
        preference: str,
        chosen_value: Any,
        question_dimension: str,
        dimension_value: Any,
        evidence: str,
        lightmem_ref: str = "",
    ) -> PreferenceRecord:
        question_dimension, dimension_value = _normalize_condition(
            question_dimension,
            dimension_value,
        )
        if question_dimension == "default":
            condition = Condition(type="default")
        else:
            condition = Condition(
                type=question_dimension,
                operator="==",
                target=dimension_value,
            )
        record, _ = self.preference_table.upsert_preference(
            preference=preference,
            value=chosen_value,
            condition=condition,
            source="learned_from_clarification",
            evidence=evidence,
            lightmem_ref=lightmem_ref or evidence,
        )
        return record

    def learn_from_dialogue(
        self,
        *,
        context: str,
        question: str,
        answer: str,
        tool_name: str,
        tool_args: Mapping[str, Any],
        retrieved_prefs: Sequence[Mapping[str, Any]],
    ) -> PreferenceRecord:
        if self.llm_client is None:
            raise ValueError("ClarificationLearner requires llm_client for dialogue learning.")
        raw = self.llm_client.complete(
            messages=[
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "context": context,
                            "question": question,
                            "answer": answer,
                            "tool_name": tool_name,
                            "tool_args": dict(tool_args),
                            "retrieved_prefs": list(retrieved_prefs),
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        payload = _load_json_payload(raw)
        if payload is None:
            repaired = self.llm_client.complete(
                messages=[
                    {"role": "system", "content": self.RETRY_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            "请把下面这次澄清学习任务的输出修复成合法 JSON。\n\n"
                            f"原始任务:\n{self.SYSTEM_PROMPT}\n\n"
                            "输入:\n"
                            f"{json.dumps({'context': context, 'question': question, 'answer': answer, 'tool_name': tool_name, 'tool_args': dict(tool_args), 'retrieved_prefs': list(retrieved_prefs)}, ensure_ascii=False)}\n\n"
                            "无效输出:\n"
                            f"{raw}"
                        ),
                    },
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            payload = _load_json_payload(repaired)
        payload = payload or {}

        preference = _normalize_preference(
            payload.get("preference"),
            tool_name=tool_name,
        )
        value = _normalize_learned_value(
            preference=preference,
            raw_value=payload.get("value", _tool_value(tool_args)),
            tool_args=tool_args,
        )
        question_dimension, dimension_value = _derive_condition_from_dialogue(
            payload=payload,
            context=context,
            question=question,
            answer=answer,
            retrieved_prefs=retrieved_prefs,
        )
        return self.learn(
            preference=preference,
            chosen_value=value,
            question_dimension=question_dimension,
            dimension_value=dimension_value,
            evidence=payload.get(
                "evidence",
                f"Learned from clarification: question={question}; answer={answer}",
            ),
            lightmem_ref=payload.get(
                "evidence",
                f"Learned from clarification: question={question}; answer={answer}",
            ),
        )

    def reconcile_learned_preference(
        self,
        learned: PreferenceRecord,
    ) -> list[PreferenceRecord]:
        if learned.condition.type != "health_state":
            return []
        target = _normalize_health_state(learned.condition.target)
        if target in {"recovering", "recovered", "healthy", "well", "better"}:
            return self.preference_table.mark_matching_expired(
                preference=learned.preference,
                condition_type="health_state",
                condition_target="sick",
            )
        return []


def _extract_json(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _load_json_payload(raw: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(_extract_json(raw))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, Mapping):
        return None
    return dict(payload)


def _tool_name_to_preference(tool_name: str) -> str:
    mapping = {
        "set_ac_temperature": "ac_temperature",
        "set_seat_heating": "seat_heating",
    }
    return mapping.get(tool_name, tool_name)


def _tool_value(tool_args: Mapping[str, Any]) -> Any:
    if "value" in tool_args:
        return tool_args["value"]
    if "level" in tool_args:
        return tool_args["level"]
    return dict(tool_args)


def _normalize_condition(condition_type: str, target: Any) -> tuple[str, Any]:
    if condition_type == "health_state":
        return condition_type, _normalize_health_state(target)
    if condition_type == "passenger_health_state":
        return condition_type, _normalize_health_state(target)
    return condition_type, target


def _normalize_preference(raw_preference: Any, *, tool_name: str) -> str:
    normalized = normalize_preference_name(raw_preference)
    if normalized is not None:
        return normalized
    inferred = infer_preference_from_text(str(raw_preference or ""))
    if inferred is not None:
        return inferred
    return _tool_name_to_preference(tool_name)


def _normalize_learned_value(
    *,
    preference: str,
    raw_value: Any,
    tool_args: Mapping[str, Any],
) -> Any:
    fallback = _tool_value(tool_args)
    if preference == "ac_temperature":
        return _parse_number(raw_value, fallback=fallback)
    if preference == "seat_heating":
        number = _parse_number(raw_value, fallback=fallback)
        try:
            return int(number)
        except (TypeError, ValueError):
            return fallback
    if preference == "music_mode":
        text = str(raw_value or "").strip().lower()
        if text in {"silent", "quiet", "mute", "安静", "不放音乐"}:
            return "silent"
        if text in {"light", "soft", "gentle", "轻音乐", "轻"}:
            return "light"
        if text in {"energizing", "energetic", "upbeat", "提神"}:
            return "energizing"
    return raw_value if raw_value not in (None, "") else fallback


def _derive_condition_from_dialogue(
    *,
    payload: Mapping[str, Any],
    context: str,
    question: str,
    answer: str,
    retrieved_prefs: Sequence[Mapping[str, Any]],
) -> tuple[str, Any]:
    condition_payload = payload.get("condition")
    condition_type = "default"
    condition_target: Any = None
    if isinstance(condition_payload, Mapping):
        condition_type = str(condition_payload.get("type") or "default").strip() or "default"
        condition_target = condition_payload.get("target")

    inferred_health = _infer_health_state_from_text(answer)
    if inferred_health is not None and _looks_like_passenger_health_clarification(
        context=context,
        question=question,
        retrieved_prefs=retrieved_prefs,
    ):
        return "passenger_health_state", inferred_health
    if inferred_health is not None and _looks_like_health_clarification(
        question=question,
        payload_condition_type=condition_type,
        retrieved_prefs=retrieved_prefs,
    ):
        return "health_state", inferred_health

    return _normalize_condition(condition_type, condition_target)


def _looks_like_passenger_health_clarification(
    *,
    context: str,
    question: str,
    retrieved_prefs: Sequence[Mapping[str, Any]],
) -> bool:
    text = f"{context}\n{question}"
    passenger_markers = ("妻子", "老婆", "爱人", "家人", "乘客", "后排", "孩子", "老公")
    if any(marker in text for marker in passenger_markers):
        return True
    for record in retrieved_prefs:
        condition = record.get("condition")
        if isinstance(condition, Mapping) and condition.get("type") == "passenger_health_state":
            return True
    return False


def _looks_like_health_clarification(
    *,
    question: str,
    payload_condition_type: str,
    retrieved_prefs: Sequence[Mapping[str, Any]],
) -> bool:
    if payload_condition_type == "health_state":
        return True
    if any(token in question for token in ("感冒", "恢复", "好些", "身体", "没好")):
        return True
    for record in retrieved_prefs:
        condition = record.get("condition")
        if isinstance(condition, Mapping) and condition.get("type") == "health_state":
            return True
    return False


def _normalize_health_state(target: Any) -> Any:
    text = str(target or "").strip().lower()
    mapping = {
        "sick": "sick",
        "ill": "sick",
        "感冒": "sick",
        "生病": "sick",
        "recovering": "recovering",
        "recovered": "recovering",
        "better": "recovering",
        "well": "healthy",
        "healthy": "healthy",
        "好多了": "recovering",
        "好些了": "recovering",
        "基本恢复": "recovering",
        "差不多好了": "recovering",
        "快好了": "recovering",
        "恢复了": "recovering",
        "恢复中": "recovering",
        "康复": "recovering",
        "康复了": "recovering",
        "痊愈": "healthy",
        "完全康复了": "recovering",
        "好了": "recovering",
    }
    return mapping.get(text, target)


def _infer_health_state_from_text(text: str) -> str | None:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return None
    healthy_markers = (
        "完全康复",
        "完全好了",
        "痊愈",
        "healthy",
    )
    recovering_markers = (
        "好多了",
        "好些了",
        "基本恢复",
        "差不多好了",
        "快好了",
        "恢复了",
        "恢复中",
        "康复了",
        "康复中",
        "好了",
        "better",
    )
    sick_markers = (
        "还没好",
        "没好",
        "还难受",
        "不舒服",
        "感冒着",
        "sick",
        "ill",
    )
    if any(marker.lower() in normalized for marker in healthy_markers):
        return "healthy"
    if any(marker.lower() in normalized for marker in recovering_markers):
        return "recovering"
    if any(marker.lower() in normalized for marker in sick_markers):
        return "sick"
    return None


def _parse_number(value: Any, *, fallback: Any) -> Any:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    text = str(value or "").strip()
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if match:
        return float(match.group(0))
    return fallback
