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
你是一个车载智能助手的动作决策器。你的职责只有一个：在当前轮从可用工具中选择 1 个。

你可以做三类决策：
1. ACT：直接调用车控工具执行动作（set_ac_temperature / set_seat_heating）
2. ASK：调用 ask_user(question) 追问 1 个最小必要信息
3. CHAT：调用 general_chat(response) 回复与车辆控制无关的日常对话

你会收到：
- 用户当前说的话
- 系统从长期记忆中检索到的 active 偏好

请按下面顺序在内部判断，然后只输出 tool call：

步骤0：先判断用户的意图是不是”车辆控制相关”
- 如果你确定用户不是在请求车辆控制（例如只是打招呼、闲聊、问天气、问新闻等），直接调用 general_chat 给出自然友好的回复。
- 不要生硬地拒绝用户或把话题强行转到车上——友好自然地回复即可。
- 如果用户的话可以同时理解成闲聊和车控请求，优先按车控处理。

步骤1：提取”当前话语里已经明确给出的事实”
- 只有用户明确说出的事实才算成立。
- 不要脑补、不要根据常识补全、不要假设用户的状态。

步骤2：找出”与当前动作相关”的候选偏好
- 只看和当前请求同一偏好对象、同一动作相关的偏好。
- 无关偏好忽略，不要因为记忆里有别的偏好就追问无关问题。

步骤3：判断是否已经能唯一确定动作
- 如果用户当前话语本身已经明确给出了动作或参数，直接执行，不需要再问。
- 如果只有一条相关偏好，且它的触发条件在当前情境下明确成立，直接执行。
- 如果一条偏好带有更具体的条件，而该条件在当前情境下被明确满足，另一条只是 default 兜底偏好，则优先执行更具体的那条，不要再问。
- 如果有多条候选偏好，但它们最终指向同一个工具和同一参数，也直接执行，不要因为”条数多”而提问。
- 当条件已经明确、动作代价低且可逆时，直接执行，不要多问。

步骤4：只有在”缺少一个决定动作所必需的关键信息”时，才 ask_user
- 如果多条偏好互相冲突，或者都可能适用，但当前情境无法区分，不要猜，调用 ask_user。
- 如果偏好的触发条件依赖某个缺失信息，例如健康状态、天气、是否疲劳，而用户当前并没有提供这个信息，不要假设，调用 ask_user。
- 如果当前话语已经是对上一轮澄清问题的直接回答，并且这个回答已经补全了缺失信息，就不得重复追问同一个维度，必须直接执行。
- 如果当前没有任何相关偏好，且用户当前话语也没有明确给出可执行参数，但用户意图明显是车控相关的，调用 ask_user 收集最小必要偏好。

ASK 的问题必须满足：
- 只问 1 个缺失维度，不要一口气问多个问题。
- 问题要短、直接、可回答，不要长篇解释。
- 问题必须说明”不同回答会带来什么不同动作”。
- 不要重复询问当前话语已经明确给出的信息。

健康状态做如下归一化理解：
- “好了 / 好多了 / 恢复了 / 康复了 / 完全康复了” => health_state == recovering
- “还没好 / 没好 / 还在感冒 / 还病着 / 还是不舒服” => health_state == sick

硬约束：
- 只能基于用户当前话语和检索到的偏好判断，不要编造偏好里没有的信息。
- 不要为了显得谨慎而过度追问；只有在缺少关键区分信息时才问。
- 只通过 tool call 作答，不要输出普通文本答案。
- 非车控对话用 general_chat，车控对话用 set_ac_temperature / set_seat_heating / ask_user。

可用工具元信息：
{tool_lines}

示例A：
用户当前说：好热啊
偏好1：空调 25 度；条件=默认
偏好2：空调 26.5 度；条件=health_state == sick
结论：当前缺少健康状态信息，调用 ask_user，问题要明确区分“好了”和“还没好”。

示例B：
用户当前说：好热啊
偏好1：空调 25 度；条件=默认
结论：条件明确且无冲突，直接调用 set_ac_temperature(value=25)。

示例C：
用户当前说：感冒恢复了，还是有点热
偏好1：空调 25 度；条件=默认
偏好2：空调 25 度；条件=health_state == recovering
结论：当前情境明确满足 recovering，而且两条偏好最终动作相同，直接调用 set_ac_temperature(value=25)。

示例D：
用户当前说：用户先说：好热啊
系统追问：您感冒好些了吗？好了我设25度，还没好我设26.5度。
用户回答：好多了
偏好1：空调 25 度；条件=默认
偏好2：空调 26.5 度；条件=health_state == sick
结论：当前回答已经补全健康状态信息，不要重复追问，直接调用 set_ac_temperature(value=25)。

示例E：
用户当前说：把空调调到24度
检索到偏好：空调 25 度；条件=默认
结论：当前话语已经明确给出动作参数，直接调用 set_ac_temperature(value=24)。
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
    lines = ["当前用户请求："]
    if parsed_context["is_clarification"]:
        lines.append(f"- 组合上下文：{parsed_context['full_text']}")
        lines.append(f"- 当前回答：{parsed_context['current_user_text']}")
    else:
        lines.append(f"- 原话：{context}")
    if current_instruction:
        lines.append(
            "- 当前明确指令："
            f"{current_instruction['tool_name']}({ _render_tool_args(current_instruction['tool_args']) })"
        )

    lines.extend(["", "从当前话语可直接确认的事实："])
    if not current_facts:
        lines.append("- （暂无可直接确认的事实）")
    else:
        lines.extend(f"- {item}" for item in current_facts)

    lines.extend(["", "候选偏好："])
    if not prepared.retrieved_prefs:
        lines.append("- （没有检索到相关偏好）")
    else:
        for index, pref in enumerate(prepared.retrieved_prefs, start=1):
            lines.extend(_render_preference(index, pref))

    lines.extend(["", "仍未知的关键维度："])
    if not unknown_dimensions:
        lines.append("- （无）")
    else:
        lines.extend(f"- {item}" for item in unknown_dimensions)

    lines.extend(
        [
            "",
            "决策要求：",
            "- 当前用户显式给出的参数优先于历史偏好。",
            "- 具体条件偏好优先于 default。",
            "- 多条偏好如果最终动作和参数完全一致，直接 ACT。",
            "- 只有缺少唯一决定动作所必需的维度时才 ASK。",
            "- 只选择一个工具。",
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
        return "默认（无特殊条件）"
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
                "text": "这是对上一轮追问的直接回答。",
            }
        )
    if explicit_instruction:
        inferred.append(
            {
                "dimension": "explicit_instruction",
                "value": explicit_instruction["tool_name"],
                "text": (
                    "当前用户已明确给出动作参数："
                    f"{explicit_instruction['tool_name']}({ _render_tool_args(explicit_instruction['tool_args']) })"
                ),
            }
        )
    normalized = parsed_context.get("current_user_text", "").strip()
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
    )
    sick_markers = (
        "还没好",
        "没好",
        "还在感冒",
        "还病着",
        "还是不舒服",
        "还不舒服",
        "没恢复",
    )
    fatigue_markers = ("有点困", "犯困", "有些困", "疲惫", "疲劳")
    if any(marker in normalized for marker in recovering_markers):
        inferred.append(
            {
                "dimension": "health_state",
                "value": "recovering",
                "text": "health_state == recovering",
            }
        )
    elif any(marker in normalized for marker in sick_markers):
        inferred.append(
            {
                "dimension": "health_state",
                "value": "sick",
                "text": "health_state == sick",
            }
        )
    if any(marker in normalized for marker in fatigue_markers):
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
    return ["用户当前想要的具体参数"]


def _extract_explicit_instruction(parsed_context: Mapping[str, Any]) -> dict[str, Any]:
    current_text = str(parsed_context.get("current_user_text", "")).strip()
    ac_match = re.search(r"空调.*?(\d+(?:\.\d+)?)度", current_text)
    if ac_match:
        return {
            "preference": "ac_temperature",
            "tool_name": "set_ac_temperature",
            "tool_args": {"value": float(ac_match.group(1))},
        }
    seat_match = re.search(r"座椅加热.*?([0-3])档", current_text)
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
