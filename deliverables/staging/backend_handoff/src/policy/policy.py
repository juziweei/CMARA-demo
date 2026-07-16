from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from src.action.car_functions import TOOLS_META, TOOLS_SCHEMA
from src.action.llm_client import ToolChatClient
from src.memory.preference_table import infer_preference_from_text, normalize_preference_name


@dataclass(frozen=True)
class Decision:
    action: str
    tool_name: str
    tool_args: dict[str, Any] = field(default_factory=dict)
    question: str = ""
    rationale: str = ""


@dataclass(frozen=True)
class PreparedPolicyInput:
    retrieved_prefs: list[dict[str, Any]]
    trace: dict[str, Any]


class PolicyError(RuntimeError):
    pass


class Policy:
    def __init__(
        self,
        *,
        llm_client: ToolChatClient,
        tools_schema: Sequence[Mapping[str, Any]] | None = None,
        tools_meta: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        self.llm = llm_client
        self.tools_schema = list(tools_schema or TOOLS_SCHEMA)
        self.tools_meta = dict(tools_meta or TOOLS_META)
        self._tool_names = {
            schema["function"]["name"]
            for schema in self.tools_schema
            if schema.get("type") == "function"
        }

    def decide(
        self, *, context: str, retrieved_prefs: Sequence[Mapping[str, Any]]
    ) -> Decision:
        prepared = self.prepare_inputs(context=context, retrieved_prefs=retrieved_prefs)
        return self.decide_prepared(context=context, prepared=prepared)

    def prepare_inputs(
        self, *, context: str, retrieved_prefs: Sequence[Mapping[str, Any]]
    ) -> PreparedPolicyInput:
        return prepare_policy_inputs(context=context, retrieved_prefs=retrieved_prefs)

    def decide_prepared(
        self, *, context: str, prepared: PreparedPolicyInput
    ) -> Decision:
        response = self.llm.chat(
            messages=[
                {"role": "system", "content": build_system_prompt(self.tools_meta)},
                {
                    "role": "user",
                    "content": _compose_user_prompt(context, prepared),
                },
            ],
            tools=self.tools_schema,
            tool_choice="auto",
            temperature=0.0,
        )
        if not response.tool_calls:
            raise PolicyError("Policy model returned no tool call.")

        tool_call = response.tool_calls[0]
        if tool_call.name not in self._tool_names:
            raise PolicyError(f"Model selected unsupported tool: {tool_call.name}")
        if tool_call.name == "ask_user":
            question = str(tool_call.arguments.get("question", "")).strip()
            if not question:
                raise PolicyError("ask_user tool call must include a non-empty question.")
            return Decision(
                action="ASK",
                tool_name="ask_user",
                tool_args=dict(tool_call.arguments),
                question=question,
                rationale=response.content,
            )
        return Decision(
            action="ACT",
            tool_name=tool_call.name,
            tool_args=dict(tool_call.arguments),
            rationale=response.content,
        )


def build_system_prompt(
    tools_meta: Mapping[str, Mapping[str, Any]] | None = None,
) -> str:
    tool_lines = "\n".join(_render_tool_meta(tools_meta or TOOLS_META))
    return f"""
You are the action decision module for an in-car intelligent assistant. Your only job is to choose exactly one available tool for the current turn.

You can make two kinds of decisions:
1. ACT: directly call a vehicle-control tool.
2. ASK: call ask_user(question) to ask for one minimal missing piece of information.

You will receive:
- the current user utterance
- active preferences retrieved from long-term memory

Reason internally in this order, then output only a tool call:

Step 1: Extract facts explicitly stated in the current utterance.
- Only facts explicitly stated by the user count.
- Do not infer, assume, or fill in missing user state from common sense.

Step 2: Identify candidate preferences relevant to the requested action.
- Only use preferences about the same control object/action as the current request.
- Ignore unrelated preferences. Do not ask about unrelated memory.

Step 3: Decide whether the action is already uniquely identifiable.
- If the current utterance explicitly gives an action or parameter, execute it directly.
- If exactly one relevant preference applies and its condition is clearly satisfied, execute it directly.
- If a specific conditional preference is clearly satisfied and another candidate is only a default fallback, prefer the specific preference and do not ask.
- If multiple candidates lead to the same tool and same argument, execute directly.
- If the condition is clear and the action is low-cost and reversible, execute directly.

Step 4: Ask only when one action-critical dimension is missing.
- If multiple preferences conflict or could apply, and the current context cannot distinguish them, do not guess; call ask_user.
- If a preference condition depends on missing information such as health state, weather, or fatigue, and the user did not provide it, ask.
- If the current utterance is already a direct answer to the previous clarification question and it resolves the missing dimension, do not ask again; execute.
- If there is no relevant preference and the user did not provide an executable parameter, ask for the minimal necessary preference.

ASK question requirements:
- Ask only one missing dimension.
- Keep the question short, direct, and easy to answer.
- Explain what different answers will do.
- Do not ask for information already stated by the user.
- The question must be written in English.

Health-state normalization:
- "better / recovered / recovering / basically recovered / much better / feeling better" => health_state == recovering
- "still sick / not recovered / still have a cold / still uncomfortable" => health_state == sick

Hard constraints:
- Use only the current utterance and retrieved preferences. Do not invent missing preferences.
- Do not over-ask just to be cautious. Ask only when a key distinguishing dimension is missing.
- Use only tool calls. Do not output normal text.
- All natural-language arguments, especially ask_user(question), must be in English.

Available tool metadata:
{tool_lines}

Example A:
Current user utterance: It feels hot.
Preference 1: AC 25 C; condition=default
Preference 2: AC 26.5 C; condition=health_state == sick
Conclusion: health state is missing. Call ask_user with an English question that distinguishes "recovered" from "still sick".

Example B:
Current user utterance: It feels hot.
Preference 1: AC 25 C; condition=default
Conclusion: condition is clear and there is no conflict. Call set_ac_temperature(value=25).

Example C:
Current user utterance: I have recovered from the cold, but it still feels hot.
Preference 1: AC 25 C; condition=default
Preference 2: AC 25 C; condition=health_state == recovering
Conclusion: recovering is explicit and both preferences lead to the same action. Call set_ac_temperature(value=25).

Example D:
Current user utterance:
Original user request: It feels hot.
System clarification question: Are you feeling better from the cold? If you have recovered, I will set 25 C; if you are still sick, I will set 26.5 C.
User clarification answer: I feel much better today.
Preference 1: AC 25 C; condition=default
Preference 2: AC 26.5 C; condition=health_state == sick
Conclusion: the answer resolves health state. Do not ask again. Call set_ac_temperature(value=25).

Example E:
Current user utterance: Set the AC to 24 degrees.
Retrieved preference: AC 25 C; condition=default
Conclusion: the current utterance explicitly gives a parameter. Call set_ac_temperature(value=24).
""".strip()


def build_user_prompt(
    context: str, retrieved_prefs: Sequence[Mapping[str, Any]]
) -> str:
    prepared = prepare_policy_inputs(context=context, retrieved_prefs=retrieved_prefs)
    return _compose_user_prompt(context, prepared)


def prepare_policy_inputs(
    *, context: str, retrieved_prefs: Sequence[Mapping[str, Any]]
) -> PreparedPolicyInput:
    parsed_context = _parse_context(context)
    explicit_instruction = _extract_explicit_instruction(parsed_context)
    current_facts = _infer_context_facts(parsed_context, explicit_instruction)
    normalized_prefs = [_normalize_policy_pref(pref) for pref in retrieved_prefs]
    primary_preference = explicit_instruction.get("preference") or infer_preference_from_text(
        parsed_context["full_text"]
    )
    filtered_prefs, filtered_out = _filter_candidates(
        normalized_prefs,
        primary_preference=primary_preference,
    )
    merged_prefs = _merge_candidates(filtered_prefs)
    unknown_dimensions = _infer_unknown_dimensions(
        merged_prefs,
        current_facts=current_facts,
        explicit_instruction=explicit_instruction,
    )
    trace = {
        "context": context,
        "parsed_context": parsed_context,
        "current_instruction": explicit_instruction or None,
        "current_facts": [fact["text"] for fact in current_facts],
        "primary_preference": primary_preference,
        "raw_retrieved_prefs": normalized_prefs,
        "filtered_out_preferences": filtered_out,
        "policy_candidates": merged_prefs,
        "unknown_dimensions": unknown_dimensions,
    }
    return PreparedPolicyInput(retrieved_prefs=merged_prefs, trace=trace)


def _compose_user_prompt(context: str, prepared: PreparedPolicyInput) -> str:
    trace = prepared.trace
    parsed_context = trace["parsed_context"]
    current_instruction = trace["current_instruction"]
    current_facts = trace["current_facts"]
    unknown_dimensions = trace["unknown_dimensions"]
    lines = ["Current user request:"]
    if parsed_context["is_clarification"]:
        lines.append(f"- Combined context: {parsed_context['full_text']}")
        lines.append(f"- Current answer: {parsed_context['current_user_text']}")
    else:
        lines.append(f"- Raw utterance: {context}")
    if current_instruction:
        lines.append(
            "- Explicit current instruction: "
            f"{current_instruction['tool_name']}({ _render_tool_args(current_instruction['tool_args']) })"
        )

    lines.extend(["", "Facts directly confirmed by the current utterance:"])
    if not current_facts:
        lines.append("- no directly confirmed facts")
    else:
        lines.extend(f"- {item}" for item in current_facts)

    lines.extend(["", "Candidate preferences:"])
    if not prepared.retrieved_prefs:
        lines.append("- no relevant preferences retrieved")
    else:
        for index, pref in enumerate(prepared.retrieved_prefs, start=1):
            lines.extend(_render_preference(index, pref))

    lines.extend(["", "Still-unknown key dimensions:"])
    if not unknown_dimensions:
        lines.append("- none")
    else:
        lines.extend(f"- {item}" for item in unknown_dimensions)

    lines.extend(
        [
            "",
            "Decision requirements:",
            "- Explicit parameters in the current user utterance override historical preferences.",
            "- Specific conditional preferences override default preferences.",
            "- If multiple preferences lead to exactly the same action and arguments, ACT directly.",
            "- ASK only when a dimension necessary to uniquely decide the action is missing.",
            "- Select exactly one tool.",
            "- If asking, the question must be in English.",
        ]
    )
    return "\n".join(lines)


def _render_preference(index: int, pref: Mapping[str, Any]) -> list[str]:
    condition = pref.get("condition") or {}
    lines = [f"{index}. candidate"]
    lines.append(f"  - preference: {pref.get('preference')}")
    lines.append(f"  - value: {pref.get('value')}")
    lines.append(f"  - condition.type: {condition.get('type', '-')}")
    lines.append(f"  - condition.operator: {condition.get('operator', '-')}")
    lines.append(f"  - condition.target: {condition.get('target', '-')}")
    lines.append(f"  - source: {pref.get('source', 'unknown')}")
    lines.append(f"  - evidence: {pref.get('evidence', '') or '-'}")
    lines.append(f"  - matched_by: {pref.get('matched_by', '') or '-'}")
    if pref.get("tool_name"):
        lines.append(
            f"  - action_candidate: {pref['tool_name']}({ _render_tool_args(pref.get('tool_args', {})) })"
        )
    condition_text = pref.get("condition_text") or _condition_to_text(condition)
    lines.append(f"  - condition_text: {condition_text}")
    supporting = pref.get("supporting_condition_texts") or []
    if supporting:
        lines.append(f"  - supporting_conditions: {'; '.join(supporting)}")
    if pref.get("supporting_ids"):
        lines.append(
            "  - supporting_ids: "
            + ", ".join(str(item) for item in pref.get("supporting_ids", []))
        )
    return lines


def _condition_to_text(condition: Any) -> str:
    if not isinstance(condition, Mapping):
        return str(condition)
    if condition.get("type") == "default":
        return "default, no special condition"
    if condition.get("type") == "merged":
        supporting = condition.get("supporting_conditions") or []
        if supporting:
            return "merged: " + "; ".join(_condition_to_text(item) for item in supporting)
        return "merged"
    if "operator" in condition and "target" in condition:
        return f"{condition['type']} {condition['operator']} {condition['target']}"
    return str(condition)


def _render_tool_meta(
    tools_meta: Mapping[str, Mapping[str, Any]]
) -> Iterable[str]:
    for name, meta in tools_meta.items():
        yield (
            f"- {name}: cost={meta.get('cost', 'unknown')}, "
            f"reversible={meta.get('reversible', 'unknown')}"
        )


def _parse_context(context: str) -> dict[str, Any]:
    text = context.strip()
    match = re.search(
        r"用户先说：(.*?)\n系统追问：(.*?)\n用户回答：(.*)",
        text,
        re.DOTALL,
    )
    if not match:
        match = re.search(
            r"Original user request:\s*(.*?)\n"
            r"System clarification question:\s*(.*?)\n"
            r"User clarification answer:\s*(.*)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
    if not match:
        return {
            "is_clarification": False,
            "full_text": text,
            "original_context": text,
            "system_question": "",
            "current_user_text": text,
        }
    return {
        "is_clarification": True,
        "full_text": text,
        "original_context": match.group(1).strip(),
        "system_question": match.group(2).strip(),
        "current_user_text": match.group(3).strip(),
    }


def _infer_context_facts(
    parsed_context: Mapping[str, Any],
    explicit_instruction: Mapping[str, Any],
) -> list[dict[str, str]]:
    inferred: list[dict[str, str]] = []
    if parsed_context.get("is_clarification"):
        inferred.append(
            {
                "dimension": "clarification",
                "value": "answered",
                "text": "This is a direct answer to the previous clarification question.",
            }
        )
    if explicit_instruction:
        inferred.append(
            {
                "dimension": "explicit_instruction",
                "value": explicit_instruction["tool_name"],
                "text": (
                    "The current user utterance explicitly provides the action parameter: "
                    f"{explicit_instruction['tool_name']}({ _render_tool_args(explicit_instruction['tool_args']) })"
                ),
            }
        )
    normalized = parsed_context.get("current_user_text", "").strip()
    lowered = normalized.lower()
    recovering_markers = (
        "好多了",
        "好些了",
        "好了",
        "恢复了",
        "恢复中",
        "基本恢复",
        "差不多好了",
        "快好了",
        "康复了",
        "完全康复了",
        "better",
        "much better",
        "feeling better",
        "recovered",
        "recovering",
        "basically recovered",
    )
    sick_markers = (
        "还没好",
        "没好",
        "还在感冒",
        "还病着",
        "还是不舒服",
        "还不舒服",
        "没恢复",
        "still sick",
        "not recovered",
        "still have a cold",
        "still uncomfortable",
        "not feeling well",
    )
    fatigue_markers = (
        "有点困",
        "犯困",
        "有些困",
        "疲惫",
        "疲劳",
        "sleepy",
        "drowsy",
        "tired",
        "fatigued",
    )
    if any(marker in lowered for marker in recovering_markers):
        inferred.append(
            {
                "dimension": "health_state",
                "value": "recovering",
                "text": "health_state == recovering",
            }
        )
    elif any(marker in lowered for marker in sick_markers):
        inferred.append(
            {
                "dimension": "health_state",
                "value": "sick",
                "text": "health_state == sick",
            }
        )
    if any(marker in lowered for marker in fatigue_markers):
        inferred.append(
            {
                "dimension": "fatigue_state",
                "value": "sleepy",
                "text": "fatigue_state == sleepy",
            }
        )
    return inferred


def _normalize_policy_pref(pref: Mapping[str, Any]) -> dict[str, Any]:
    normalized_preference = normalize_preference_name(pref.get("preference")) or str(
        pref.get("preference", "")
    )
    condition = dict(pref.get("condition") or {"type": "default"})
    tool_name, tool_args = _preference_to_action(normalized_preference, pref.get("value"))
    return {
        "id": pref.get("id", "?"),
        "preference": normalized_preference,
        "value": pref.get("value"),
        "condition": condition,
        "condition_text": pref.get("condition_text") or _condition_to_text(condition),
        "status": pref.get("status", "active"),
        "source": pref.get("source", "unknown"),
        "evidence": str(pref.get("evidence", "")).strip(),
        "timestamp": pref.get("timestamp", ""),
        "matched_by": str(pref.get("matched_by", "")).strip(),
        "retrieval_score": int(pref.get("retrieval_score") or 0),
        "query_score": int(pref.get("query_score") or 0),
        "tool_name": tool_name,
        "tool_args": tool_args,
    }


def _filter_candidates(
    prefs: Sequence[Mapping[str, Any]],
    *,
    primary_preference: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    normalized = [dict(pref) for pref in prefs]
    if not normalized:
        return [], []
    if primary_preference:
        kept = [pref for pref in normalized if pref.get("preference") == primary_preference]
        filtered = [pref for pref in normalized if pref.get("preference") != primary_preference]
        return kept or normalized, filtered if kept else []

    group_scores: dict[str, int] = {}
    for pref in normalized:
        key = str(pref.get("preference", ""))
        group_scores[key] = group_scores.get(key, 0) + int(pref.get("retrieval_score", 0)) + int(
            pref.get("query_score", 0)
        )
    if len(group_scores) <= 1:
        return normalized, []
    max_score = max(group_scores.values())
    if max_score <= 0:
        return normalized, []
    threshold = max(1, int(max_score * 0.7))
    kept_names = {name for name, score in group_scores.items() if score >= threshold}
    kept = [pref for pref in normalized if pref.get("preference") in kept_names]
    filtered = [pref for pref in normalized if pref.get("preference") not in kept_names]
    return kept, filtered


def _merge_candidates(prefs: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for pref in prefs:
        key = _candidate_group_key(pref)
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(dict(pref))

    merged: list[dict[str, Any]] = []
    for key in order:
        group = grouped[key]
        if len(group) == 1:
            merged.append(group[0])
            continue
        first = group[0]
        supporting_conditions = _dedupe_dicts([item.get("condition") or {} for item in group])
        supporting_condition_texts = list(
            dict.fromkeys(item.get("condition_text") or _condition_to_text(item.get("condition")) for item in group)
        )
        supporting_ids = [item.get("id") for item in group]
        merged.append(
            {
                **first,
                "id": supporting_ids[0],
                "condition": {
                    "type": "merged",
                    "supporting_conditions": supporting_conditions,
                },
                "condition_text": "merged: " + "; ".join(supporting_condition_texts),
                "source": ", ".join(
                    dict.fromkeys(str(item.get("source", "unknown")) for item in group)
                ),
                "evidence": " | ".join(
                    evidence
                    for evidence in dict.fromkeys(
                        str(item.get("evidence", "")).strip() for item in group
                    )
                    if evidence
                ),
                "matched_by": " | ".join(
                    reason
                    for reason in dict.fromkeys(
                        str(item.get("matched_by", "")).strip() for item in group
                    )
                    if reason
                ),
                "supporting_conditions": supporting_conditions,
                "supporting_condition_texts": supporting_condition_texts,
                "supporting_ids": supporting_ids,
                "retrieval_score": sum(int(item.get("retrieval_score", 0)) for item in group),
                "query_score": sum(int(item.get("query_score", 0)) for item in group),
                "converged_action": True,
            }
        )
    return merged


def _candidate_group_key(pref: Mapping[str, Any]) -> str:
    action_signature = _action_signature(pref)
    if action_signature:
        return f"{pref.get('preference')}::{action_signature}"
    return f"{pref.get('preference')}::{json.dumps(pref.get('value'), ensure_ascii=False, sort_keys=True)}"


def _action_signature(pref: Mapping[str, Any]) -> str:
    tool_name = pref.get("tool_name")
    if not tool_name:
        return ""
    return tool_name + "::" + json.dumps(pref.get("tool_args") or {}, ensure_ascii=False, sort_keys=True)


def _infer_unknown_dimensions(
    prefs: Sequence[Mapping[str, Any]],
    *,
    current_facts: Sequence[Mapping[str, Any]],
    explicit_instruction: Mapping[str, Any],
) -> list[str]:
    if explicit_instruction:
        return []
    action_signatures = {
        _action_signature(pref)
        or f"{pref.get('preference')}::{json.dumps(pref.get('value'), ensure_ascii=False, sort_keys=True)}"
        for pref in prefs
    }
    if len(action_signatures) <= 1:
        return []
    known_dimensions = {
        str(fact.get("dimension"))
        for fact in current_facts
        if fact.get("dimension") not in {"clarification", "explicit_instruction"}
    }
    unresolved: list[str] = []
    for pref in prefs:
        conditions = pref.get("supporting_conditions") or [pref.get("condition") or {}]
        for condition in conditions:
            condition_type = str(condition.get("type", ""))
            if not condition_type or condition_type in {"default", "merged"}:
                continue
            if condition_type in known_dimensions:
                continue
            unresolved.append(condition_type)
    unique = list(dict.fromkeys(unresolved))
    if unique:
        return unique
    return ["the concrete parameter the user wants now"]


def _extract_explicit_instruction(parsed_context: Mapping[str, Any]) -> dict[str, Any]:
    current_text = str(parsed_context.get("current_user_text", "")).strip()
    lowered = current_text.lower()
    ac_match = re.search(r"空调.*?(\d+(?:\.\d+)?)度", current_text)
    if not ac_match:
        ac_match = re.search(
            r"(?:ac|air conditioning|air conditioner|climate|temperature).*?"
            r"(\d+(?:\.\d+)?)\s*(?:c|°c|degrees?|deg)?",
            lowered,
        )
    if ac_match:
        return {
            "preference": "ac_temperature",
            "tool_name": "set_ac_temperature",
            "tool_args": {"value": float(ac_match.group(1))},
        }
    seat_match = re.search(r"座椅加热.*?([0-3])档", current_text)
    if not seat_match:
        seat_match = re.search(
            r"(?:seat heating|seat heater|heated seat).*?([0-3])",
            lowered,
        )
    if seat_match:
        return {
            "preference": "seat_heating",
            "tool_name": "set_seat_heating",
            "tool_args": {"level": int(seat_match.group(1))},
        }
    if "关掉座椅加热" in current_text or "座椅加热关掉" in current_text:
        return {
            "preference": "seat_heating",
            "tool_name": "set_seat_heating",
            "tool_args": {"level": 0},
        }
    if any(text in lowered for text in ("turn off seat heating", "seat heating off", "turn off the seat heater")):
        return {
            "preference": "seat_heating",
            "tool_name": "set_seat_heating",
            "tool_args": {"level": 0},
        }
    return {}


def _preference_to_action(
    preference: str, value: Any
) -> tuple[str, dict[str, Any]]:
    if preference == "ac_temperature":
        try:
            return "set_ac_temperature", {"value": float(value)}
        except (TypeError, ValueError):
            return "set_ac_temperature", {"value": value}
    if preference == "seat_heating":
        try:
            return "set_seat_heating", {"level": int(value)}
        except (TypeError, ValueError):
            return "set_seat_heating", {"level": value}
    return "", {}


def _render_tool_args(arguments: Mapping[str, Any]) -> str:
    parts = []
    for key, value in arguments.items():
        if isinstance(value, float):
            parts.append(f"{key}={value:g}")
        else:
            parts.append(f"{key}={value}")
    return ", ".join(parts) or "-"


def _dedupe_dicts(items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        marker = json.dumps(dict(item), ensure_ascii=False, sort_keys=True)
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(dict(item))
    return deduped
