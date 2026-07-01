from __future__ import annotations

from dataclasses import dataclass

from src.action.car_functions import TOOLS_SCHEMA
from src.action.assistant_responder import AssistantResponder
from src.action.llm_client import OpenAIToolClient
from src.config import DemoConfig
from src.interface.session import DemoSession
from src.memory.clarification_learner import ClarificationLearner
from src.memory.lightmem_store import LightMemStore
from src.memory.offline_summarizer import OfflineSummarizer
from src.memory.preference_table import PreferenceTable
from src.policy.policy import Policy


@dataclass(frozen=True)
class RuntimeBundle:
    session: DemoSession
    preference_table: PreferenceTable
    summarizer: OfflineSummarizer


def build_runtime(settings: DemoConfig | None = None) -> RuntimeBundle:
    settings = settings or DemoConfig()
    llm_client = OpenAIToolClient(
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        api_key=settings.llm_api_key,
    )
    policy = Policy(llm_client=llm_client, tools_schema=TOOLS_SCHEMA)
    lightmem_store = LightMemStore.from_settings(settings)
    preference_table = PreferenceTable(settings.preferences_path)
    summarizer = OfflineSummarizer(
        llm_client=llm_client,
        preference_table=preference_table,
    )
    responder = AssistantResponder(llm_client=llm_client)
    learner = ClarificationLearner(preference_table, llm_client=llm_client)
    session = DemoSession(
        policy=policy,
        memory_store=lightmem_store,
        preference_table=preference_table,
        learner=learner,
        responder=responder,
    )
    return RuntimeBundle(
        session=session,
        preference_table=preference_table,
        summarizer=summarizer,
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
