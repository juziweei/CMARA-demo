from __future__ import annotations

from typing import Any, Sequence

from src.action.llm_client import ToolChatClient
from src.memory.direct_preference_extractor import DirectPreferenceExtractor
from src.memory.preference_table import PreferenceRecord, PreferenceTable


class OfflineSummarizer:
    def __init__(
        self,
        *,
        llm_client: ToolChatClient,
        preference_table: PreferenceTable,
    ) -> None:
        self.preference_table = preference_table
        self.extractor = DirectPreferenceExtractor(llm_client=llm_client)

    def summarize(
        self, messages: Sequence[dict[str, Any]]
    ) -> list[PreferenceRecord]:
        if not messages:
            return []

        result = self.extractor.extract(messages)
        added: list[PreferenceRecord] = []
        for item in result.preferences:
            record, created = self.preference_table.upsert_preference(
                preference=item.preference,
                value=item.value,
                condition=item.condition,
                source="offline_summary",
                evidence=item.evidence,
                lightmem_ref=item.evidence,
            )
            if created:
                added.append(record)
        return added
