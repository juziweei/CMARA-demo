from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.interface.runtime import RuntimeBundle, build_runtime as _build_runtime_bundle
from src.memory.offline_summarizer import OfflineSummarizer
from src.memory.preference_table import Condition, PreferenceRecord, PreferenceTable
from src.interface.session import DemoSession


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _render_preferences(records: Iterable[PreferenceRecord]) -> str:
    items = list(records)
    if not items:
        return "(no structured preferences yet)"
    lines = []
    for record in items:
        lines.append(
            f"[{record.id}] {record.preference}={record.value} | "
            f"{record.condition.describe()} | {record.status} | {record.source} | "
            f"{record.evidence}"
        )
    return "\n".join(lines)


def _handle_remember(command: str, session: DemoSession) -> str:
    parts = command.split(" ", 5)
    if len(parts) < 5:
        raise ValueError(
            "Usage: /remember <preference> <value> <condition_type> <condition_target|-> [evidence]"
        )
    _, preference, value_text, condition_type, condition_target, *rest = parts
    evidence = rest[0] if rest else f"Manually added at {_now()}"
    condition = (
        Condition(type="default")
        if condition_type == "default"
        else Condition(
            type=condition_type,
            operator="==",
            target=None if condition_target == "-" else condition_target,
        )
    )
    value: float | str
    try:
        value = float(value_text)
    except ValueError:
        value = value_text
    record = session.remember_preference(
        preference=preference,
        value=value,
        condition=condition.to_dict(),
        source="user_stated",
        evidence=evidence,
    )
    return f"Stored preference [{record.id}] {record.preference}={record.value}."


def build_runtime() -> tuple[
    DemoSession,
    PreferenceTable,
    OfflineSummarizer,
]:
    bundle: RuntimeBundle = _build_runtime_bundle()
    return bundle.session, bundle.preference_table, bundle.summarizer


def main() -> None:
    parser = argparse.ArgumentParser(description="Vehicle memory demo CLI.")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print decision trace for each turn.",
    )
    args = parser.parse_args()

    try:
        session, preference_table, summarizer = build_runtime()
    except Exception as exc:
        print(f"Failed to start demo runtime: {exc}")
        print("Run `python3 scripts/check_runtime.py` first and fix the reported environment issues.")
        return
    print("Vehicle memory demo CLI. Commands: /memory /forget <id> /remember ... /summarize /quit")

    while True:
        raw = input("user> ").strip()
        if not raw:
            continue
        if raw == "/quit":
            break
        if raw == "/memory":
            print(_render_preferences(preference_table.list_preferences()))
            continue
        if raw.startswith("/forget "):
            record_id = int(raw.split(maxsplit=1)[1])
            deleted = preference_table.forget(record_id)
            print(f"Removed [{record_id}]." if deleted else f"[{record_id}] not found.")
            continue
        if raw.startswith("/remember "):
            print(_handle_remember(raw, session))
            continue
        if raw == "/summarize":
            additions = summarizer.summarize(session.session_messages)
            if additions:
                print("Offline summary created:")
                print(_render_preferences(additions))
            else:
                print("Offline summary found no new preference.")
            continue

        result = session.handle_user_message(raw)
        print(f"assistant> {result.assistant_text}")
        if args.debug:
            print("trace>")
            print(json.dumps(result.decision_trace, ensure_ascii=False, indent=2))

        if result.status == "needs_user_input":
            follow_up = input("user> ").strip()
            if not follow_up:
                continue
            if result.pending is None:
                raise RuntimeError("missing pending clarification state")
            follow_up_result = session.handle_clarification(result.pending, follow_up)
            print(f"assistant> {follow_up_result.assistant_text}")
            if args.debug:
                print("trace>")
                print(json.dumps(follow_up_result.decision_trace, ensure_ascii=False, indent=2))
            if follow_up_result.expired_preferences:
                print(
                    "assistant> expired: "
                    + ", ".join(
                        f"[{record.id}] {record.preference} ({record.condition.describe()})"
                        for record in follow_up_result.expired_preferences
                    )
                )
            if follow_up_result.learned_preference is not None:
                learned = follow_up_result.learned_preference
                print(
                    "assistant> learned: "
                    f"[{learned.id}] {learned.preference}={learned.value} | "
                    f"{learned.condition.describe()}"
                )
        else:
            continue


if __name__ == "__main__":
    main()
