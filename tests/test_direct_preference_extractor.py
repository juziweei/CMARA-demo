from __future__ import annotations

from src.memory.direct_preference_extractor import (
    _extract_preferences_payload,
    _normalize_condition,
    _normalize_extracted_item,
    _normalize_music_mode,
)


def test_extract_preferences_payload_handles_code_fenced_json() -> None:
    raw = """```json
    {"preferences": [{"preference": "music_mode", "value": "light", "condition": {"type": "default"}, "evidence": "放点轻音乐"}]}
    ```"""

    payload = _extract_preferences_payload(raw)

    assert payload == [
        {
            "preference": "music_mode",
            "value": "light",
            "condition": {"type": "default"},
            "evidence": "放点轻音乐",
        }
    ]


def test_normalize_extracted_item_applies_whitelist_and_value_mapping() -> None:
    item = {
        "preference": "音乐",
        "value": "轻音乐",
        "condition": {"type": "trip_scene", "operator": "==", "target": "family_trip"},
        "evidence": "如果大家都醒着而且路况平稳，就放点轻音乐。",
    }

    extracted = _normalize_extracted_item(item)

    assert extracted is not None
    assert extracted.preference == "music_mode"
    assert extracted.value == "light"
    assert extracted.condition.to_dict() == {
        "type": "trip_scene",
        "operator": "==",
        "target": "family_trip",
    }


def test_normalize_condition_and_music_mode_map_expected_aliases() -> None:
    assert _normalize_music_mode("提神") == "energizing"
    assert _normalize_condition(
        {"type": "weather_state", "operator": "==", "target": "下雨"}
    ).to_dict() == {
        "type": "weather_state",
        "operator": "==",
        "target": "rainy",
    }


def test_normalize_extracted_item_rejects_passenger_state_as_user_state() -> None:
    item = {
        "preference": "music_mode",
        "value": "silent",
        "condition": {"type": "fatigue_state", "operator": "==", "target": "sleepy"},
        "evidence": "后排两个孩子都睡着的时候，最好不要主动放音乐。",
    }

    extracted = _normalize_extracted_item(item)

    assert extracted is None
