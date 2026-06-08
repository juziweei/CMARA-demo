from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Literal, Sequence

from src.memory.lightmem_store import MemoryHit

PreferenceStatus = Literal["active", "expired"]
PreferenceSource = Literal[
    "user_stated", "offline_summary", "learned_from_clarification"
]

_UNSET = object()

_PREFERENCE_ALIASES: dict[str, tuple[str, ...]] = {
    "ac_temperature": ("ac", "temperature", "空调", "温度", "热", "冷"),
    "seat_heating": ("seat", "heating", "座椅", "加热"),
    "music_mode": ("music", "音乐", "安静", "吵", "播放"),
}
_PREFERENCE_NAME_MAP: dict[str, str] = {
    "ac_temperature": "ac_temperature",
    "ac": "ac_temperature",
    "temperature": "ac_temperature",
    "air_conditioner": "ac_temperature",
    "空调": "ac_temperature",
    "空调温度": "ac_temperature",
    "车内温度": "ac_temperature",
    "seat_heating": "seat_heating",
    "seat_heat": "seat_heating",
    "seat heater": "seat_heating",
    "座椅加热": "seat_heating",
    "加热座椅": "seat_heating",
    "music_mode": "music_mode",
    "music": "music_mode",
    "音乐": "music_mode",
    "播放音乐": "music_mode",
}
SUPPORTED_PREFERENCES = frozenset(_PREFERENCE_ALIASES)


@dataclass(frozen=True)
class Condition:
    type: str
    operator: str | None = None
    target: Any = None
    unit: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"type": self.type}
        if self.operator is not None:
            payload["operator"] = self.operator
        if self.target is not None:
            payload["target"] = self.target
        if self.unit is not None:
            payload["unit"] = self.unit
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Condition":
        return cls(
            type=payload["type"],
            operator=payload.get("operator"),
            target=payload.get("target"),
            unit=payload.get("unit"),
        )

    def describe(self) -> str:
        if self.type == "default":
            return "默认（无特殊条件）"
        if self.operator is not None and self.target is not None:
            suffix = f" {self.unit}" if self.unit else ""
            return f"{self.type} {self.operator} {self.target}{suffix}"
        return self.type


@dataclass(frozen=True)
class PreferenceRecord:
    id: int
    preference: str
    value: Any
    condition: Condition
    status: PreferenceStatus
    source: PreferenceSource
    evidence: str
    lightmem_ref: str
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "preference": self.preference,
            "value": self.value,
            "condition": self.condition.to_dict(),
            "status": self.status,
            "source": self.source,
            "evidence": self.evidence,
            "lightmem_ref": self.lightmem_ref,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PreferenceRecord":
        return cls(
            id=int(payload["id"]),
            preference=payload["preference"],
            value=payload["value"],
            condition=Condition.from_dict(payload["condition"]),
            status=payload["status"],
            source=payload["source"],
            evidence=payload.get("evidence", ""),
            lightmem_ref=payload.get("lightmem_ref", ""),
            timestamp=payload.get("timestamp", date.today().isoformat()),
        )

    def search_text(self) -> str:
        fields = [
            self.preference,
            str(self.value),
            self.condition.describe(),
            self.evidence,
            self.lightmem_ref,
        ]
        return " ".join(part for part in fields if part)

    def to_policy_payload(
        self,
        *,
        matched_by: str = "",
        retrieval_score: int | None = None,
        query_score: int | None = None,
    ) -> dict[str, Any]:
        payload = {
            "id": self.id,
            "preference": self.preference,
            "value": self.value,
            "condition": self.condition.to_dict(),
            "condition_text": self.condition.describe(),
            "status": self.status,
            "source": self.source,
            "evidence": self.evidence,
            "timestamp": self.timestamp,
        }
        if matched_by:
            payload["matched_by"] = matched_by
        if retrieval_score is not None:
            payload["retrieval_score"] = retrieval_score
        if query_score is not None:
            payload["query_score"] = query_score
        return payload

    def dedupe_key(self) -> tuple[str, str, str]:
        return (
            self.preference,
            json.dumps(self.condition.to_dict(), ensure_ascii=False, sort_keys=True),
            json.dumps(self.value, ensure_ascii=False, sort_keys=True),
        )


@dataclass(frozen=True)
class PreferenceMatch:
    record: PreferenceRecord
    retrieval_score: int
    query_score: int
    total_score: int
    matched_by: str


class PreferenceTable:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("[]", encoding="utf-8")

    def list_preferences(self) -> list[PreferenceRecord]:
        return self._load()

    def get_active(self, preference: str | None = None) -> list[PreferenceRecord]:
        return [
            record
            for record in self._load()
            if record.status == "active"
            and (preference is None or record.preference == preference)
        ]

    def add_preference(
        self,
        *,
        preference: str,
        value: Any,
        condition: Condition,
        source: PreferenceSource,
        evidence: str,
        lightmem_ref: str = "",
        timestamp: str | None = None,
    ) -> PreferenceRecord:
        records = self._load()
        next_id = max((record.id for record in records), default=0) + 1
        record = PreferenceRecord(
            id=next_id,
            preference=preference,
            value=value,
            condition=condition,
            status="active",
            source=source,
            evidence=evidence,
            lightmem_ref=lightmem_ref,
            timestamp=timestamp or date.today().isoformat(),
        )
        records.append(record)
        self._save(records)
        return record

    def find_matching_active(
        self,
        *,
        preference: str,
        value: Any,
        condition: Condition,
    ) -> PreferenceRecord | None:
        probe = PreferenceRecord(
            id=-1,
            preference=preference,
            value=value,
            condition=condition,
            status="active",
            source="user_stated",
            evidence="",
            lightmem_ref="",
            timestamp=date.today().isoformat(),
        )
        for record in self._load():
            if record.status != "active":
                continue
            if record.dedupe_key() == probe.dedupe_key():
                return record
        return None

    def upsert_preference(
        self,
        *,
        preference: str,
        value: Any,
        condition: Condition,
        source: PreferenceSource,
        evidence: str,
        lightmem_ref: str = "",
        timestamp: str | None = None,
    ) -> tuple[PreferenceRecord, bool]:
        records = self._load()
        candidate = PreferenceRecord(
            id=-1,
            preference=preference,
            value=value,
            condition=condition,
            status="active",
            source=source,
            evidence=evidence,
            lightmem_ref=lightmem_ref,
            timestamp=timestamp or date.today().isoformat(),
        )
        for index, record in enumerate(records):
            if record.status != "active":
                continue
            if record.dedupe_key() != candidate.dedupe_key():
                continue
            updated = PreferenceRecord(
                id=record.id,
                preference=record.preference,
                value=record.value,
                condition=record.condition,
                status="active",
                source=source,
                evidence=evidence,
                lightmem_ref=lightmem_ref or record.lightmem_ref,
                timestamp=timestamp or record.timestamp,
            )
            records[index] = updated
            self._save(records)
            return updated, False
        return self.add_preference(
            preference=preference,
            value=value,
            condition=condition,
            source=source,
            evidence=evidence,
            lightmem_ref=lightmem_ref,
            timestamp=timestamp,
        ), True

    def mark_expired(self, record_id: int) -> PreferenceRecord | None:
        records = self._load()
        updated: PreferenceRecord | None = None
        rewritten: list[PreferenceRecord] = []
        for record in records:
            if record.id == record_id:
                updated = PreferenceRecord(
                    id=record.id,
                    preference=record.preference,
                    value=record.value,
                    condition=record.condition,
                    status="expired",
                    source=record.source,
                    evidence=record.evidence,
                    lightmem_ref=record.lightmem_ref,
                    timestamp=record.timestamp,
                )
                rewritten.append(updated)
            else:
                rewritten.append(record)
        if updated is None:
            return None
        self._save(rewritten)
        return updated

    def mark_matching_expired(
        self,
        *,
        preference: str | None = None,
        condition_type: str | None = None,
        condition_target: Any = _UNSET,
    ) -> list[PreferenceRecord]:
        matched: list[PreferenceRecord] = []
        rewritten: list[PreferenceRecord] = []
        for record in self._load():
            should_expire = record.status == "active"
            if preference is not None:
                should_expire = should_expire and record.preference == preference
            if condition_type is not None:
                should_expire = should_expire and record.condition.type == condition_type
            if condition_target is not _UNSET:
                should_expire = should_expire and record.condition.target == condition_target
            if should_expire:
                expired = PreferenceRecord(
                    id=record.id,
                    preference=record.preference,
                    value=record.value,
                    condition=record.condition,
                    status="expired",
                    source=record.source,
                    evidence=record.evidence,
                    lightmem_ref=record.lightmem_ref,
                    timestamp=record.timestamp,
                )
                matched.append(expired)
                rewritten.append(expired)
            else:
                rewritten.append(record)
        if matched:
            self._save(rewritten)
        return matched

    def forget(self, record_id: int) -> bool:
        records = self._load()
        kept = [record for record in records if record.id != record_id]
        if len(kept) == len(records):
            return False
        self._save(kept)
        return True

    def update_by_id(
        self,
        record_id: int,
        *,
        preference: str | None = None,
        value: Any = _UNSET,
        condition: Condition | None = None,
        status: PreferenceStatus | None = None,
        source: PreferenceSource | None = None,
        evidence: str | None = None,
    ) -> PreferenceRecord | None:
        records = self._load()
        for index, record in enumerate(records):
            if record.id != record_id:
                continue
            updated = PreferenceRecord(
                id=record.id,
                preference=preference if preference is not None else record.preference,
                value=record.value if value is _UNSET else value,
                condition=condition if condition is not None else record.condition,
                status=status if status is not None else record.status,
                source=source if source is not None else record.source,
                evidence=evidence if evidence is not None else record.evidence,
                lightmem_ref=record.lightmem_ref,
                timestamp=record.timestamp,
            )
            records[index] = updated
            self._save(records)
            return updated
        return None

    def find_relevant(
        self,
        *,
        query_text: str,
        lightmem_hits: Sequence[MemoryHit | str],
        limit: int = 5,
    ) -> list[PreferenceRecord]:
        return [
            match.record
            for match in self.find_relevant_matches(
                query_text=query_text,
                lightmem_hits=lightmem_hits,
                limit=limit,
            )
        ]

    def find_relevant_matches(
        self,
        *,
        query_text: str,
        lightmem_hits: Sequence[MemoryHit | str],
        limit: int = 5,
    ) -> list[PreferenceMatch]:
        active = self.get_active()
        hits = [_coerce_hit(hit) for hit in lightmem_hits]
        scored: list[PreferenceMatch] = []
        for record in active:
            retrieval_score, retrieval_reason = _score_record(record, hits)
            query_score, query_reason = _score_query(record, query_text)
            total_score = retrieval_score + (query_score * 3)
            if total_score <= 0:
                continue
            scored.append(
                PreferenceMatch(
                    record=record,
                    retrieval_score=retrieval_score,
                    query_score=query_score,
                    total_score=total_score,
                    matched_by=_combine_reasons(retrieval_reason, query_reason),
                )
            )
        scored.sort(key=lambda item: (-item.total_score, item.record.id))
        return scored[:limit]

    def _load(self) -> list[PreferenceRecord]:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return [PreferenceRecord.from_dict(item) for item in payload]

    def _save(self, records: Iterable[PreferenceRecord]) -> None:
        payload = [record.to_dict() for record in records]
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def normalize_preference_name(raw: Any) -> str | None:
    text = str(raw or "").strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered in _PREFERENCE_NAME_MAP:
        return _PREFERENCE_NAME_MAP[lowered]
    for canonical, aliases in _PREFERENCE_ALIASES.items():
        if lowered == canonical:
            return canonical
        if any(alias.lower() == lowered for alias in aliases):
            return canonical
    return None


def infer_preference_from_text(text: str) -> str | None:
    lowered = str(text or "").lower()
    best_name = None
    best_score = 0
    for canonical, aliases in _PREFERENCE_ALIASES.items():
        score = 0
        for alias in aliases:
            if alias.lower() in lowered:
                score += max(1, len(alias))
        if score > best_score:
            best_name = canonical
            best_score = score
    return best_name if best_score > 0 else None


def _score_record(
    record: PreferenceRecord, hits: Sequence[MemoryHit]
) -> tuple[int, str]:
    if not hits:
        return 0, ""
    score = 0
    reasons: list[str] = []
    for hit in hits:
        hit_text = hit.memory.lower().strip()
        if not hit_text:
            continue
        ref_text = record.lightmem_ref.lower().strip()
        evidence_text = record.evidence.lower().strip()
        if ref_text and (ref_text in hit_text or hit_text in ref_text):
            score += 100
            reasons.append(f"hit:{_reason_snippet(hit.memory)}")
        elif evidence_text and (evidence_text in hit_text or hit_text in evidence_text):
            score += 80
            reasons.append(f"evidence:{_reason_snippet(hit.memory)}")
        for fragment in _record_fragments(record):
            normalized = fragment.lower()
            if normalized and normalized in hit_text:
                score += max(1, len(normalized))
                if len(reasons) < 2:
                    reasons.append(f"fragment:{fragment}")
        score += _token_overlap(record.search_text(), hit_text)
        if hit.score is not None:
            score += int(hit.score * 10)
    return score, " / ".join(dict.fromkeys(reasons))


def _score_query(record: PreferenceRecord, query_text: str) -> tuple[int, str]:
    query = str(query_text or "").strip().lower()
    if not query:
        return 0, ""
    score = 0
    reasons: list[str] = []
    for fragment in _query_fragments(record):
        normalized = fragment.lower().strip()
        if not normalized:
            continue
        if normalized in query:
            score += max(1, len(normalized))
            if len(reasons) < 3:
                reasons.append(fragment)
    score += _token_overlap(" ".join(_query_fragments(record)), query) * 2
    if not reasons and score <= 0:
        return 0, ""
    return score, "query:" + ", ".join(dict.fromkeys(reasons))


def _coerce_hit(hit: MemoryHit | str) -> MemoryHit:
    if isinstance(hit, MemoryHit):
        return hit
    return MemoryHit(id=f"coerced-{hash(hit)}", memory=str(hit))


def _record_fragments(record: PreferenceRecord) -> Iterable[str]:
    yield record.preference
    for alias in _PREFERENCE_ALIASES.get(record.preference, ()):
        yield alias
    yield str(record.value)
    if record.condition.target is not None:
        yield str(record.condition.target)
    if record.lightmem_ref:
        yield record.lightmem_ref
    if record.evidence:
        yield record.evidence


def _query_fragments(record: PreferenceRecord) -> list[str]:
    fragments = [record.preference, *_PREFERENCE_ALIASES.get(record.preference, ())]
    if record.condition.target is not None:
        fragments.append(str(record.condition.target))
    return fragments


def _token_overlap(left: str, right: str) -> int:
    left_tokens = set(_tokenize(left))
    right_tokens = set(_tokenize(right))
    return len(left_tokens & right_tokens)


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[\w\u4e00-\u9fff]+", text.lower())


def _reason_snippet(text: str, *, limit: int = 24) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def _combine_reasons(*reasons: str) -> str:
    kept = [reason for reason in reasons if reason]
    return " | ".join(dict.fromkeys(kept))
