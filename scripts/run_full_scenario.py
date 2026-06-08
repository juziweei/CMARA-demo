from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.action.car_functions import TOOLS_SCHEMA
from src.action.llm_client import OpenAIToolClient
from src.config import DemoConfig
from src.interface.session import DemoSession
from src.memory.clarification_learner import ClarificationLearner
from src.memory.lightmem_store import LightMemStore
from src.memory.offline_summarizer import OfflineSummarizer
from src.memory.preference_table import Condition, PreferenceTable
from src.policy.policy import Policy


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the multi-day vehicle memory demo.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset local demo persistence before running the scenario.",
    )
    args = parser.parse_args()

    settings = DemoConfig()
    if args.reset:
        _reset_demo_state(settings)

    try:
        client = OpenAIToolClient(
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            api_key=settings.llm_api_key,
        )
        policy = Policy(llm_client=client, tools_schema=TOOLS_SCHEMA)
        lightmem_store = LightMemStore.from_settings(settings)
        table = PreferenceTable(settings.preferences_path)
        learner = ClarificationLearner(table, llm_client=client)
        summarizer = OfflineSummarizer(
            llm_client=client,
            preference_table=table,
        )
        session = DemoSession(
            policy=policy,
            memory_store=lightmem_store,
            preference_table=table,
            learner=learner,
        )
    except Exception as exc:
        print(f"Failed to initialize full scenario runtime: {exc}")
        print("Run `python3 scripts/check_runtime.py` and fix the missing model path / vLLM service first.")
        return

    _seed_user_stated_preferences(session)
    _print_preferences(table, "After seeding user_stated preferences")

    day_dialogue = [
        "关音乐吧，太吵了。",
        "今天开车想安静一点。",
        "还是别放音乐了。",
    ]
    for text in day_dialogue:
        session.session_messages.append(
            {"role": "user", "content": text, "time_stamp": "2026-05-03T18:00:00"}
        )
        lightmem_store.add([session.session_messages[-1]])
    summary = summarizer.summarize(session.session_messages[-3:])
    print("Offline summary output:")
    print(json.dumps([record.to_dict() for record in summary], ensure_ascii=False, indent=2))
    _print_preferences(table, "After offline summary")

    initial = session.handle_user_message("好热啊")
    print("First hot turn:")
    print(_render_turn(initial))
    if initial.pending is None:
        raise RuntimeError("Expected clarification on the first hot turn.")

    resolved = session.handle_clarification(initial.pending, "好多了")
    print("Clarified turn:")
    print(_render_turn(resolved))
    _print_preferences(table, "After clarification learning and expiration")

    repeat = session.handle_user_message("感冒恢复了，还是有点热")
    print("Repeat recovery turn:")
    print(_render_turn(repeat))
    _print_preferences(table, "Final preferences")


def _reset_demo_state(settings: DemoConfig) -> None:
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
    history_db = settings.history_db_path
    if history_db.exists():
        history_db.unlink()


def _seed_user_stated_preferences(session: DemoSession) -> None:
    if session.preference_table.list_preferences():
        return
    session.remember_preference(
        preference="ac_temperature",
        value=25,
        condition={"type": "default"},
        source="user_stated",
        evidence="用户说空调 25 度比较舒服",
    )
    session.remember_preference(
        preference="ac_temperature",
        value=26.5,
        condition={"type": "health_state", "operator": "==", "target": "sick"},
        source="user_stated",
        evidence="用户说感冒时空调调高一点",
    )


def _print_preferences(table: PreferenceTable, title: str) -> None:
    print(title + ":")
    for record in table.list_preferences():
        print(
            f"  [{record.id}] {record.preference}={record.value} | "
            f"{record.condition.describe()} | {record.status} | {record.source}"
        )
    print("-" * 60)


def _render_turn(result) -> str:
    lines = [
        f"status={result.status}",
        f"assistant={result.assistant_text}",
        f"decision={result.decision}",
    ]
    if result.tool_result is not None:
        lines.append(f"tool_result={result.tool_result}")
    if result.learned_preference is not None:
        lines.append(f"learned={result.learned_preference.to_dict()}")
    if result.expired_preferences:
        lines.append(
            "expired="
            + json.dumps(
                [record.to_dict() for record in result.expired_preferences],
                ensure_ascii=False,
            )
        )
    return "\n".join(lines)


if __name__ == "__main__":
    main()
