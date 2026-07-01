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
from src.memory.preference_table import PreferenceTable
from src.policy.policy import Policy


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a family trip long-term memory scenario."
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset local demo persistence before running the scenario.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print decision trace for each scenario turn.",
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
        print(f"Failed to initialize family trip runtime: {exc}")
        print(
            "Run `python3 scripts/check_runtime.py` and fix the missing model path / vLLM service first."
        )
        return

    print("=== Family Trip Long-Term Memory Scenario ===")
    print("Story: a family is going out on multiple trips, and the car assistant gradually learns stable preferences.")
    print()

    _seed_family_trip_preferences(session)
    _print_preferences(table, "Day 0 · Seeded family-trip preferences")

    family_trip_dialogue = [
        ("这周末一家人去海边，先导航到东堤停车场吧。", "已规划去东堤停车场的路线。"),
        ("后备箱里有野餐垫、儿童推车和一箱水，别忘了。", "已记录出游物品提醒。"),
        ("姐姐刚在后排睡着了，先别放音乐。", "好的，先保持车内安静。"),
        ("等会儿如果堵车，就走滨海高架，不要穿市区。", "明白，拥堵时优先绕行滨海高架。"),
        ("孩子一坐长途车就容易闹，车里安静一点会舒服很多。", "已记住长途出游时优先保持安静。"),
        ("爸爸想听歌也先等等，别把孩子吵醒。", "收到，暂时不主动播放音乐。"),
        ("到服务区前提醒我给孩子拿小饼干和晕车贴。", "好的，接近服务区时提醒您。"),
        ("一家人出去玩的时候，我一般不想车里太吵。", "已记录家庭出游时偏好安静环境。"),
        ("如果孩子醒了再说，现在就别播歌了。", "明白，当前保持静音。"),
        ("海边风大，到了以后提醒我给孩子加件外套。", "好的，到海边后提醒您。"),
        ("路上要是太晒就把遮阳帘拉一下，但现在先不用。", "收到，暂不操作遮阳帘。"),
        ("今天主要是轻松出游，车里保持安静就好。", "好的，维持安静出游模式。"),
        ("后排两个孩子都睡着的时候，最好不要主动放音乐。", "已记录孩子睡着时不主动放音乐。"),
        ("等到快下高速再提醒我看一下餐厅排队情况。", "好的，下高速前提醒您查看餐厅排队。"),
    ]
    dialogue_messages = []
    for user_text, assistant_text in family_trip_dialogue:
        turn_messages = [
            {
                "role": "user",
                "content": user_text,
                "time_stamp": "2026-06-01T20:00:00",
            },
            {
                "role": "assistant",
                "content": assistant_text,
                "time_stamp": "2026-06-01T20:00:01",
            },
        ]
        session.session_messages.extend(turn_messages)
        dialogue_messages.extend(turn_messages)
        lightmem_store.add(turn_messages)
    summary = summarizer.summarize(dialogue_messages)
    print("Day 1 night · Offline family-trip summary:")
    print(f"Input dialogue turns for offline summary: {len(family_trip_dialogue)}")
    print(json.dumps([record.to_dict() for record in summary], ensure_ascii=False, indent=2))
    _print_preferences(table, "After offline summary")

    initial = session.handle_user_message("周末一家人要去海边了，好热啊。")
    print("Day 2 departure · First hot turn:")
    print(_render_turn(initial, debug=args.debug))
    if initial.pending is None:
        raise RuntimeError("Expected clarification on the first family-trip hot turn.")

    resolved = session.handle_clarification(initial.pending, "好多了，今天基本恢复了。")
    print("Day 2 departure · Clarified turn:")
    print(_render_turn(resolved, debug=args.debug))
    _print_preferences(table, "After clarification learning and expiration")

    repeat = session.handle_user_message("下周一家人又要去郊游了，感冒恢复了，还是有点热。")
    print("Day 9 departure · Repeat family-trip turn:")
    print(_render_turn(repeat, debug=args.debug))
    _print_preferences(table, "Final family-trip preferences")


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
    if settings.history_db_path.exists():
        settings.history_db_path.unlink()


def _seed_family_trip_preferences(session: DemoSession) -> None:
    if session.preference_table.list_preferences():
        return
    session.remember_preference(
        preference="ac_temperature",
        value=24,
        condition={"type": "default"},
        source="user_stated",
        evidence="用户说一家人出去玩时，车里空调 24 度最舒服。",
    )
    session.remember_preference(
        preference="ac_temperature",
        value=25.5,
        condition={"type": "health_state", "operator": "==", "target": "sick"},
        source="user_stated",
        evidence="用户说如果自己还在感冒，带家人出门时空调别太冷，25.5 度更舒服。",
    )


def _print_preferences(table: PreferenceTable, title: str) -> None:
    print(title + ":")
    for record in table.list_preferences():
        print(
            f"  [{record.id}] {record.preference}={record.value} | "
            f"{record.condition.describe()} | {record.status} | {record.source}"
        )
    print("-" * 60)


def _render_turn(result, *, debug: bool = False) -> str:
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
    if debug:
        lines.append(
            "decision_trace="
            + json.dumps(result.decision_trace, ensure_ascii=False, indent=2)
        )
    return "\n".join(lines)


if __name__ == "__main__":
    main()
