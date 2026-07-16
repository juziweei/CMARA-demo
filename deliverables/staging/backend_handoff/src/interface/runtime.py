from __future__ import annotations

from dataclasses import dataclass

from src.action.car_functions import TOOLS_SCHEMA
from src.action.assistant_responder import AssistantResponder
from src.action.llm_client import OpenAIToolClient
from src.config import DemoConfig
from src.interface.session import DemoSession
from src.memory.clarification_learner import ClarificationLearner
from src.memory.lightmem_store import LightMemStore, MemoryHit
from src.memory.offline_summarizer import OfflineSummarizer
from src.memory.preference_table import PreferenceTable
from src.policy.policy import Policy


@dataclass(frozen=True)
class RuntimeBundle:
    session: DemoSession
    preference_table: PreferenceTable
    summarizer: OfflineSummarizer
    memory_mode: str


def build_runtime(settings: DemoConfig | None = None) -> RuntimeBundle:
    settings = settings or DemoConfig()
    llm_client = OpenAIToolClient(
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        api_key=settings.llm_api_key,
    )
    policy = Policy(llm_client=llm_client, tools_schema=TOOLS_SCHEMA)
    memory_store, memory_mode = _build_memory_store(settings)
    preference_table = PreferenceTable(settings.preferences_path)
    summarizer = OfflineSummarizer(
        llm_client=llm_client,
        preference_table=preference_table,
    )
    responder = AssistantResponder(llm_client=llm_client)
    learner = ClarificationLearner(preference_table, llm_client=llm_client)
    session = DemoSession(
        policy=policy,
        memory_store=memory_store,
        preference_table=preference_table,
        learner=learner,
        responder=responder,
    )
    return RuntimeBundle(
        session=session,
        preference_table=preference_table,
        summarizer=summarizer,
        memory_mode=memory_mode,
    )


def reset_demo_state(settings: DemoConfig | None = None) -> None:
    settings = settings or DemoConfig()
    settings.ensure_storage()
    settings.preferences_path.write_text("[]\n", encoding="utf-8")
    if settings.qdrant_path.exists():
        for path in settings.qdrant_path.iterdir():
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                for nested in sorted(path.rglob("*"), reverse=True):
                    if nested.is_file():
                        nested.unlink()
                    elif nested.is_dir():
                        nested.rmdir()
                path.rmdir()
    if settings.history_db_path.exists():
        settings.history_db_path.unlink()


def _build_memory_store(settings: DemoConfig) -> tuple[object, str]:
    try:
        store = LightMemStore.from_settings(settings)
        return store, "lightmem"
    except Exception:
        return SimpleMemoryStore(), "simple"


class SimpleMemoryStore:
    def __init__(self) -> None:
        self._messages: list[dict[str, str]] = []

    def add(
        self,
        messages,
        *,
        force_segment: bool = False,
        force_extract: bool = False,
    ) -> dict[str, object]:
        del force_segment, force_extract
        for message in messages:
            self._messages.append(
                {
                    "role": str(message.get("role", "")),
                    "content": str(message.get("content", "")),
                    "time_stamp": str(message.get("time_stamp", "")),
                    "speaker_name": str(message.get("speaker_name", "")),
                }
            )
        return {"messages": list(messages), "mode": "simple"}

    def retrieve(self, query: str, limit: int = 5) -> list[str]:
        return [hit.render() for hit in self.retrieve_records(query, limit=limit)]

    def retrieve_records(self, query: str, limit: int = 5) -> list[MemoryHit]:
        query_text = str(query or "").lower()
        hits: list[MemoryHit] = []
        for index, message in enumerate(reversed(self._messages), start=1):
            content = message.get("content", "")
            score = _simple_overlap_score(query_text, content.lower())
            if score <= 0:
                continue
            hits.append(
                MemoryHit(
                    id=f"simple-{index}",
                    memory=content,
                    time_stamp=message.get("time_stamp", ""),
                    speaker_name=message.get("speaker_name", ""),
                    score=float(score),
                    payload=dict(message),
                )
            )
        hits.sort(key=lambda hit: hit.score or 0, reverse=True)
        return hits[:limit]


def _simple_overlap_score(query: str, text: str) -> int:
    if not query or not text:
        return 0
    score = 0
    for token in query.split():
        if token and token in text:
            score += max(1, len(token))
    for token in text.split():
        if token and token in query:
            score += 1
    return score
