from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from src.action.llm_client import ToolChatClient
from src.memory.preference_table import Condition, normalize_preference_name

SUPPORTED_CONDITION_TYPES = frozenset(
    {
        "default",
        "health_state",
        "fatigue_state",
        "weather_state",
        "trip_scene",
        "passenger_health_state",
    }
)
USER_STATE_CONDITION_TYPES = frozenset(
    {"health_state", "fatigue_state", "passenger_health_state"}
)
PASSENGER_SUBJECT_HINTS = (
    "孩子",
    "后排",
    "宝宝",
    "乘客",
    "姐姐",
    "弟弟",
    "女儿",
    "儿子",
    "妻子",
    "老婆",
    "爱人",
    "家人",
    "老公",
)
FIRST_PERSON_HINTS = ("我", "自己", "本人")


@dataclass(frozen=True)
class ExtractedPreference:
    preference: str
    value: Any
    condition: Condition
    evidence: str

    def dedupe_key(self) -> tuple[str, str, str]:
        return (
            self.preference,
            json.dumps(self.condition.to_dict(), ensure_ascii=False, sort_keys=True),
            json.dumps(self.value, ensure_ascii=False, sort_keys=True),
        )


@dataclass(frozen=True)
class PreferenceExtractionResult:
    raw_response: str
    repaired_response: str | None
    raw_items: list[dict[str, Any]]
    preferences: list[ExtractedPreference]
    parse_failed: bool


class DirectPreferenceExtractor:
    SYSTEM_PROMPT = """
你是车载长期偏好抽取器。你的任务不是总结当天发生了什么，而是从整段对话里抽取“用户对车内控制项的持久偏好”。

只抽这 3 类对象：
- ac_temperature
- seat_heating
- music_mode

只在满足以下条件时才输出一条偏好：
1. 用户明确表达了自己更喜欢/更习惯/更希望如何设置；
2. 这个设置可复用，不是一次性事件；
3. 能落到受控对象、受控 value、受控 condition。

不要抽：
- 一次性事件、路线、停车、取快递、孩子抢零食、天气描述本身；
- 单纯的当前状态，如果没有导向一个明确偏好设置；
- 助手代用户做的推断；
- 泛化空话，比如“舒服一点”“别太极端”，如果没有明确对象和值。

标准化要求：
1. preference 只能是：
   - "ac_temperature"
   - "seat_heating"
   - "music_mode"
2. value：
   - ac_temperature: 数字，单位摄氏度，例如 26、24.5
   - seat_heating: 整数档位，例如 2、3
   - music_mode: 只能是 "silent" | "light" | "energizing"
3. condition：
   - 默认场景：{"type":"default"}
   - 特定场景只允许以下 type：
     - {"type":"health_state","operator":"==","target":"sick"}
     - {"type":"passenger_health_state","operator":"==","target":"sick"}
     - {"type":"fatigue_state","operator":"==","target":"sleepy"}
     - {"type":"weather_state","operator":"==","target":"rainy"}
     - {"type":"trip_scene","operator":"==","target":"family_trip"}
4. evidence：
   - 必须是用户原话里的短证据，尽量贴近原句，不要写解释。

重要规则：
- 如果用户说的是“感冒没好时 26 度舒服”，这是一条有条件偏好，不是当天事件。
- 如果用户说“平时通勤 24.5 度更顺手”，这是 default 偏好。
- 如果用户只说“后排孩子在睡觉”，但没有接着说“别放音乐/想安静”，不要把它当偏好。
- 如果同一段里同时出现 default 和 specific，两条都可以输出。
- 宁缺毋滥，不要输出不确定项。

输出必须是 JSON，且只输出：
{
  "preferences": [
    {
      "preference": "ac_temperature",
      "value": 26.0,
      "condition": {"type":"health_state","operator":"==","target":"sick"},
      "evidence": "如果我感冒还没完全好，空调调到 26 度会舒服一些。"
    }
  ]
}

如果没有符合条件的偏好，输出 {"preferences": []}。
""".strip()

    RETRY_SYSTEM_PROMPT = """
你是 JSON 修复器。你的任务是把上一次的无效输出修复成合法 JSON。
不要添加解释，不要添加 markdown 代码块，只返回 JSON。
""".strip()

    def __init__(self, *, llm_client: ToolChatClient) -> None:
        self.llm_client = llm_client

    def extract(
        self, messages: Sequence[Mapping[str, Any]]
    ) -> PreferenceExtractionResult:
        transcript = "\n".join(
            f"{message['role']}: {message['content']}" for message in messages
        )
        raw = self.llm_client.complete(
            messages=[
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": transcript},
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
        )

        raw_items = _extract_preferences_payload(raw)
        repaired_response: str | None = None
        parse_failed = False

        if raw_items is None:
            parse_failed = True
            repaired_response = self.llm_client.complete(
                messages=[
                    {"role": "system", "content": self.RETRY_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            "下面这个输出本来应该是一个 JSON 对象，顶层键是 preferences。"
                            "请修复它；如果它已经无法修复，请基于原始对话重新生成同 schema 的 JSON。\n\n"
                            "原始抽取任务:\n"
                            f"{self.SYSTEM_PROMPT}\n\n"
                            "原始对话:\n"
                            f"{transcript}\n\n"
                            "无效输出:\n"
                            f"{raw}"
                        ),
                    },
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            raw_items = _extract_preferences_payload(repaired_response)

        extracted: list[ExtractedPreference] = []
        if raw_items is not None:
            for item in raw_items:
                normalized = _normalize_extracted_item(item)
                if normalized is not None:
                    extracted.append(normalized)

        return PreferenceExtractionResult(
            raw_response=raw,
            repaired_response=repaired_response,
            raw_items=raw_items or [],
            preferences=_dedupe_preferences(extracted),
            parse_failed=raw_items is None,
        )


def _extract_preferences_payload(raw: str) -> list[dict[str, Any]] | None:
    text = _extract_json_text(raw)
    candidates = [text]
    object_candidate = _extract_json_span(text, "{", "}")
    if object_candidate and object_candidate not in candidates:
        candidates.append(object_candidate)

    for candidate in candidates:
        if not candidate:
            continue
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        preferences = payload.get("preferences")
        if isinstance(preferences, list):
            return [item for item in preferences if isinstance(item, Mapping)]
    return None


def _extract_json_text(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _extract_json_span(text: str, opener: str, closer: str) -> str:
    start = text.find(opener)
    end = text.rfind(closer)
    if start == -1 or end == -1 or end < start:
        return ""
    return text[start : end + 1].strip()


def _normalize_extracted_item(item: Mapping[str, Any]) -> ExtractedPreference | None:
    preference = normalize_preference_name(item.get("preference"))
    if preference is None:
        return None

    evidence = str(item.get("evidence", "")).strip()
    if not evidence:
        return None

    normalized_value = _normalize_value(preference, item.get("value"))
    if normalized_value is None:
        return None

    condition = _normalize_condition(item.get("condition"))
    if condition is None:
        return None
    if _condition_conflicts_with_evidence(condition, evidence):
        return None

    return ExtractedPreference(
        preference=preference,
        value=normalized_value,
        condition=condition,
        evidence=evidence,
    )


def _normalize_value(preference: str, value: Any) -> Any | None:
    if preference == "ac_temperature":
        return _parse_number(value)
    if preference == "seat_heating":
        number = _parse_number(value)
        if number is None:
            return None
        return int(number)
    if preference == "music_mode":
        return _normalize_music_mode(value)
    return None


def _normalize_music_mode(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text in {"silent", "quiet", "no_music", "no music", "mute", "安静", "不放音乐"}:
        return "silent"
    if text in {"light", "light_music", "soft", "soft music", "gentle", "轻", "轻音乐"}:
        return "light"
    if text in {"energizing", "energetic", "upbeat", "提神", "清醒"}:
        return "energizing"
    return None


def _normalize_condition(payload: Any) -> Condition | None:
    if not isinstance(payload, Mapping):
        return Condition(type="default")

    raw_type = str(payload.get("type", "default")).strip().lower()
    if not raw_type:
        raw_type = "default"
    type_name = _normalize_condition_type(raw_type)
    if type_name not in SUPPORTED_CONDITION_TYPES:
        return None
    if type_name == "default":
        return Condition(type="default")

    target = _normalize_condition_target(type_name, payload.get("target"))
    if target is None:
        return None
    operator = str(payload.get("operator") or "==").strip() or "=="
    return Condition(type=type_name, operator=operator, target=target)


def _normalize_condition_type(raw_type: str) -> str:
    mapping = {
        "default": "default",
        "health_state": "health_state",
        "health": "health_state",
        "passenger_health_state": "passenger_health_state",
        "passenger_health": "passenger_health_state",
        "family_health_state": "passenger_health_state",
        "spouse_health_state": "passenger_health_state",
        "fatigue_state": "fatigue_state",
        "fatigue": "fatigue_state",
        "weather_state": "weather_state",
        "weather": "weather_state",
        "trip_scene": "trip_scene",
        "scene": "trip_scene",
    }
    return mapping.get(raw_type, raw_type)


def _normalize_condition_target(condition_type: str, target: Any) -> str | None:
    text = str(target or "").strip().lower()
    if not text:
        return None

    if condition_type == "health_state":
        if text in {"sick", "ill", "cold", "感冒", "生病", "没好", "还没完全好"}:
            return "sick"
        return None
    if condition_type == "passenger_health_state":
        if text in {"sick", "ill", "cold", "感冒", "生病", "没好", "还没完全好", "不舒服"}:
            return "sick"
        if text in {"recovering", "recovered", "better", "好多了", "恢复了", "好些了"}:
            return "recovering"
        return None
    if condition_type == "fatigue_state":
        if text in {"sleepy", "drowsy", "tired", "困", "犯困", "瞌睡"}:
            return "sleepy"
        return None
    if condition_type == "weather_state":
        if text in {"rainy", "rain", "下雨", "雨天", "潮湿"}:
            return "rainy"
        return None
    if condition_type == "trip_scene":
        if text in {"family_trip", "family", "一家人", "家人出游", "带孩子"}:
            return "family_trip"
        return None
    return None


def _condition_conflicts_with_evidence(
    condition: Condition,
    evidence: str,
) -> bool:
    if condition.type == "passenger_health_state":
        has_passenger_subject = any(token in evidence for token in PASSENGER_SUBJECT_HINTS)
        return not has_passenger_subject

    if condition.type not in USER_STATE_CONDITION_TYPES:
        return False

    has_passenger_subject = any(token in evidence for token in PASSENGER_SUBJECT_HINTS)
    has_first_person = any(token in evidence for token in FIRST_PERSON_HINTS)
    return has_passenger_subject and not has_first_person


def _parse_number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value or "").strip()
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    return float(match.group(0))


def _dedupe_preferences(
    preferences: Sequence[ExtractedPreference],
) -> list[ExtractedPreference]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[ExtractedPreference] = []
    for preference in preferences:
        key = preference.dedupe_key()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(preference)
    return deduped
