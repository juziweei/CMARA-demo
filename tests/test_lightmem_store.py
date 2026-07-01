from __future__ import annotations

from src.memory.lightmem_store import (
    _extract_json_span,
    _merge_usage,
    _parse_lightmem_json_data,
)


def test_parse_lightmem_json_data_accepts_code_fenced_json() -> None:
    raw = """```json
    {"data": [{"source_id": 1, "fact": "User prefers quiet music."}]}
    ```"""

    parsed = _parse_lightmem_json_data(raw)

    assert parsed == [{"source_id": 1, "fact": "User prefers quiet music."}]


def test_parse_lightmem_json_data_salvages_outer_json_object() -> None:
    raw = 'prefix noise {"data": [{"source_id": 3, "relation": "Bob encouraged Alice."}]} trailing noise'

    parsed = _parse_lightmem_json_data(raw)

    assert parsed == [{"source_id": 3, "relation": "Bob encouraged Alice."}]


def test_extract_json_span_and_merge_usage() -> None:
    assert _extract_json_span("aa[1, 2, 3]bb", "[", "]") == "[1, 2, 3]"
    assert _merge_usage(
        {"prompt_tokens": 11, "completion_tokens": 5, "total_tokens": 16},
        {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
    ) == {
        "prompt_tokens": 14,
        "completion_tokens": 7,
        "total_tokens": 21,
    }
