from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from lightmem.memory.lightmem import LightMemory

from src.config import DemoConfig

_LIGHTMEM_JSON_PATCHED = False
_JSON_REPAIR_SYSTEM_PROMPT = (
    "You repair invalid JSON outputs for a memory extraction pipeline. "
    "Return only valid JSON. Do not add explanations."
)


@dataclass(frozen=True)
class MemoryHit:
    id: str
    memory: str
    time_stamp: str = ""
    speaker_name: str = ""
    score: float | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def render(self) -> str:
        prefix = " ".join(part for part in (self.time_stamp, self.speaker_name) if part).strip()
        if prefix:
            return f"{prefix} {self.memory}".strip()
        return self.memory


class LightMemStore:
    def __init__(self, lightmem: LightMemory) -> None:
        self._lightmem = lightmem

    @classmethod
    def from_settings(cls, settings: DemoConfig) -> "LightMemStore":
        _install_lightmem_json_retry_patch()
        return cls(LightMemory.from_config(settings.build_lightmem_config()))

    def add(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        force_segment: bool = False,
        force_extract: bool = False,
    ) -> dict[str, Any]:
        return self._lightmem.add_memory(
            messages=list(messages),
            force_segment=force_segment,
            force_extract=force_extract,
        )

    def retrieve(self, query: str, limit: int = 5) -> list[str]:
        return [hit.render() for hit in self.retrieve_records(query, limit=limit)]

    def retrieve_records(self, query: str, limit: int = 5) -> list[MemoryHit]:
        try:
            query_vector = self._lightmem.text_embedder.embed(query)
            results = self._lightmem.embedding_retriever.search(
                query_vector=query_vector,
                limit=limit,
                return_full=True,
            )
        except Exception:
            legacy_results = self._lightmem.retrieve(query, limit=limit)
            return [
                MemoryHit(id=f"legacy-{index}", memory=text)
                for index, text in enumerate(legacy_results)
            ]

        hits: list[MemoryHit] = []
        for result in results:
            payload = dict(result.get("payload") or {})
            hits.append(
                MemoryHit(
                    id=str(result.get("id", "")),
                    memory=str(payload.get("memory", "")),
                    time_stamp=str(payload.get("time_stamp", "")),
                    speaker_name=str(payload.get("speaker_name", "")),
                    score=float(result["score"]) if result.get("score") is not None else None,
                    payload=payload,
                )
            )
        return hits

    def offline_extract(
        self, messages: Sequence[Mapping[str, Any]]
    ) -> dict[str, Any]:
        return self.add(messages, force_segment=True, force_extract=True)


def _install_lightmem_json_retry_patch() -> None:
    global _LIGHTMEM_JSON_PATCHED
    if _LIGHTMEM_JSON_PATCHED:
        return

    from lightmem.factory.memory_manager import vllm as lightmem_vllm

    original_extract = lightmem_vllm.VllmManager._extract_with_prompt

    def patched_extract(self, *args, **kwargs):
        results = original_extract(self, *args, **kwargs)
        entry_type = kwargs.get("entry_type")
        if entry_type is None and len(args) >= 5:
            entry_type = args[4]
        if entry_type is None:
            entry_type = "factual"

        repaired_results = []
        for item in results:
            repaired_results.append(
                _repair_lightmem_result(self, item, entry_type=entry_type)
            )
        return repaired_results

    lightmem_vllm.VllmManager._extract_with_prompt = patched_extract
    _LIGHTMEM_JSON_PATCHED = True


def _repair_lightmem_result(manager, item: Any, *, entry_type: str) -> Any:
    if not isinstance(item, dict):
        return item
    if item.get("cleaned_result"):
        return item

    raw_output = item.get("output_prompt")
    if not isinstance(raw_output, str) or not raw_output.strip():
        return item

    salvaged = _parse_lightmem_json_data(raw_output)
    if salvaged:
        for entry in salvaged:
            entry["entry_type"] = entry_type
        item["cleaned_result"] = salvaged
        return item

    repaired = _retry_lightmem_json(manager, item, entry_type=entry_type)
    return repaired or item


def _retry_lightmem_json(manager, item: dict[str, Any], *, entry_type: str) -> dict[str, Any] | None:
    metadata_messages = item.get("input_prompt")
    raw_output = item.get("output_prompt", "")
    if not isinstance(metadata_messages, list) or len(metadata_messages) < 2:
        return None

    original_system = str(metadata_messages[0].get("content", ""))
    original_user = str(metadata_messages[1].get("content", ""))
    value_field = "relation" if entry_type == "relational" else "fact"
    repair_messages = [
        {"role": "system", "content": _JSON_REPAIR_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "The previous extraction output was invalid JSON.\n"
                f"Return only a valid JSON object with key \"data\" and items shaped like "
                f"{{\"source_id\": <int>, \"{value_field}\": <string>}}.\n"
                "Preserve information from the invalid output when possible. "
                "If the invalid output is unusable, redo the extraction from the original task.\n\n"
                "Original extraction instruction:\n"
                f"{original_system}\n\n"
                "Original conversation chunk:\n"
                f"{original_user}\n\n"
                "Invalid output:\n"
                f"{raw_output}"
            ),
        },
    ]

    repaired_output, repaired_usage = manager.generate_response(
        messages=repair_messages,
        response_format={"type": "json_object"},
    )
    repaired_entries = _parse_lightmem_json_data(repaired_output)
    if not repaired_entries:
        return None

    for entry in repaired_entries:
        entry["entry_type"] = entry_type

    return {
        "input_prompt": metadata_messages,
        "output_prompt": repaired_output,
        "cleaned_result": repaired_entries,
        "usage": _merge_usage(item.get("usage"), repaired_usage),
        "entry_type": entry_type,
    }


def _parse_lightmem_json_data(raw_output: str) -> list[dict[str, Any]]:
    candidates = []
    cleaned = _strip_code_fence(raw_output)
    if cleaned:
        candidates.append(cleaned)

    object_candidate = _extract_json_span(cleaned, "{", "}")
    if object_candidate and object_candidate not in candidates:
        candidates.append(object_candidate)

    list_candidate = _extract_json_span(cleaned, "[", "]")
    if list_candidate and list_candidate not in candidates:
        candidates.append(list_candidate)

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and isinstance(parsed.get("data"), list):
            return [item for item in parsed["data"] if isinstance(item, dict)]
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
    return []


def _strip_code_fence(text: str) -> str:
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text.strip())
    if match:
        return match.group(1).strip()
    return text.strip()


def _extract_json_span(text: str, opener: str, closer: str) -> str:
    start = text.find(opener)
    end = text.rfind(closer)
    if start == -1 or end == -1 or end < start:
        return ""
    return text[start : end + 1].strip()


def _merge_usage(
    original: Any, retry: Any
) -> dict[str, int]:
    base = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    if isinstance(original, dict):
        for key in base:
            base[key] += int(original.get(key, 0) or 0)
    if isinstance(retry, dict):
        for key in base:
            base[key] += int(retry.get(key, 0) or 0)
    return base
