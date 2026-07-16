from __future__ import annotations

import argparse
import shutil
import statistics
import sys
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import DemoConfig
from src.memory.lightmem_store import LightMemStore
from src.memory.preference_table import Condition, PreferenceTable


DEFAULT_QUERIES = [
    "周末一家人出游，有点热，空调怎么调？",
    "今天早上通勤有点犯困，放什么音乐？",
    "下雨天接孩子放学，车里想安静一点。",
    "感冒还没好，还是觉得热。",
    "冬天上车有点冷，座椅加热开几档？",
]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed a large multi-day memory dataset and benchmark lookup latency."
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset the dedicated benchmark dataset before seeding.",
    )
    parser.add_argument(
        "--dataset",
        default="multi_day_lookup",
        help="Benchmark dataset name under data/benchmark_lookup/.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=21,
        help="Number of distinct days to seed.",
    )
    parser.add_argument(
        "--turns-per-day",
        type=int,
        default=18,
        help="Number of dialogue turns to seed per day.",
    )
    parser.add_argument(
        "--preference-copies",
        type=int,
        default=16,
        help="How many batches of structured preferences to create.",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=20,
        help="Benchmark repetitions per query.",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=3,
        help="Warmup iterations per query before measuring.",
    )
    parser.add_argument(
        "--retrieve-limit",
        type=int,
        default=8,
        help="Top-k retrieval size for both memory and preference lookup.",
    )
    parser.add_argument(
        "--query",
        action="append",
        dest="queries",
        help="Benchmark query. Repeat the flag to add multiple queries.",
    )
    parser.add_argument(
        "--show-hits",
        action="store_true",
        help="Print the top retrieval hits and matched preferences once per query.",
    )
    args = parser.parse_args()

    settings, dataset_root = _build_settings(args.dataset)
    if args.reset:
        _reset_dataset(dataset_root)

    try:
        lightmem_store = LightMemStore.from_settings(settings)
        table = PreferenceTable(settings.preferences_path)
    except Exception as exc:
        print(f"Failed to initialize benchmark runtime: {exc}")
        print("Run `python3 scripts/check_runtime.py` and fix the embedding / vLLM runtime first.")
        return

    seeded_memory_count, seeded_pref_count = _seed_dataset(
        settings=settings,
        lightmem_store=lightmem_store,
        table=table,
        days=args.days,
        turns_per_day=args.turns_per_day,
        preference_copies=args.preference_copies,
    )

    queries = args.queries or DEFAULT_QUERIES
    print("=== Lookup Benchmark ===")
    print(f"dataset={args.dataset}")
    print(f"storage_root={dataset_root}")
    print(f"days={args.days}")
    print(f"turns_per_day={args.turns_per_day}")
    print(f"memory_messages={seeded_memory_count}")
    print(f"structured_preferences={seeded_pref_count}")
    print(f"queries={len(queries)}")
    print(f"repeat={args.repeat}")
    print(f"warmup={args.warmup}")
    print("-" * 60)

    for query in queries:
        result = _benchmark_query(
            query=query,
            lightmem_store=lightmem_store,
            table=table,
            repeat=args.repeat,
            warmup=args.warmup,
            retrieve_limit=args.retrieve_limit,
        )
        print(f"query={query}")
        print(
            "  memory_ms  "
            + _format_stats(result["memory_times_ms"])
        )
        print(
            "  pref_ms    "
            + _format_stats(result["preference_times_ms"])
        )
        print(
            "  total_ms   "
            + _format_stats(result["total_times_ms"])
        )
        print(
            f"  latest_hits={len(result['latest_hits'])} "
            f"latest_prefs={len(result['latest_preferences'])}"
        )
        if args.show_hits:
            for hit in result["latest_hits"][: min(3, len(result["latest_hits"]))]:
                print(f"    hit> {hit.render()}")
            for pref in result["latest_preferences"][: min(3, len(result["latest_preferences"]))]:
                print(
                    "    pref> "
                    f"{pref['preference']}={pref['value']} | "
                    f"{pref['condition_text']} | "
                    f"{pref.get('matched_by', '-')}"
                )
        print("-" * 60)


def _build_settings(dataset_name: str) -> tuple[DemoConfig, Path]:
    root = Path("data/benchmark_lookup") / dataset_name
    settings = replace(DemoConfig())
    settings.preferences_path = root / "preferences.json"
    settings.qdrant_path = root / "qdrant"
    settings.history_db_path = root / "history.db"
    settings.lightmem_collection = f"lookup_benchmark_{dataset_name}"
    return settings, root


def _reset_dataset(root: Path) -> None:
    if root.exists():
        shutil.rmtree(root)


def _seed_dataset(
    *,
    settings: DemoConfig,
    lightmem_store: LightMemStore,
    table: PreferenceTable,
    days: int,
    turns_per_day: int,
    preference_copies: int,
) -> tuple[int, int]:
    settings.ensure_storage()
    if table.list_preferences():
        return days * turns_per_day * 2, len(table.list_preferences())

    base_date = datetime(2026, 5, 1, 8, 0, 0)
    total_messages = 0
    for day_index in range(days):
        day_start = base_date + timedelta(days=day_index)
        for turn_index in range(turns_per_day):
            user_text, assistant_text = _dialogue_turn(day_index, turn_index)
            messages = [
                {
                    "role": "user",
                    "content": user_text,
                    "time_stamp": (day_start + timedelta(minutes=turn_index * 7)).isoformat(timespec="seconds"),
                },
                {
                    "role": "assistant",
                    "content": assistant_text,
                    "time_stamp": (day_start + timedelta(minutes=turn_index * 7, seconds=5)).isoformat(timespec="seconds"),
                },
            ]
            lightmem_store.add(messages)
            total_messages += len(messages)

    total_preferences = 0
    for copy_index in range(preference_copies):
        day_label = f"D{copy_index + 1:02d}"
        for preference, value, condition, evidence in _preference_templates(copy_index, day_label):
            table.add_preference(
                preference=preference,
                value=value,
                condition=condition,
                source="user_stated",
                evidence=evidence,
                lightmem_ref=evidence,
                timestamp=(base_date + timedelta(days=copy_index)).date().isoformat(),
            )
            total_preferences += 1
    return total_messages, total_preferences


def _dialogue_turn(day_index: int, turn_index: int) -> tuple[str, str]:
    family_slot = day_index % 3 == 0
    rainy_slot = day_index % 5 == 0
    sleepy_slot = turn_index % 4 == 0
    sick_slot = (day_index + turn_index) % 7 == 0
    hot_slot = turn_index % 3 == 0

    if hot_slot and sick_slot:
        return (
            f"第{day_index + 1}天，今天还有点感冒，车里有点热，空调别太低。",
            "收到，我会把空调保持得温和一些。",
        )
    if hot_slot and family_slot:
        return (
            f"第{day_index + 1}天周末一家人出门，后排有孩子，空调舒服一点。",
            "好的，我会按家庭出游的舒适温度处理。",
        )
    if sleepy_slot:
        return (
            f"第{day_index + 1}天早高峰有点犯困，来点别太吵但能提神的音乐。",
            "明白，我会优先选择轻一点的提神音乐。",
        )
    if rainy_slot:
        return (
            f"第{day_index + 1}天下雨天接孩子放学，车里安静一点。",
            "好的，当前保持车内安静。",
        )
    if turn_index % 2 == 0:
        return (
            f"第{day_index + 1}天晚上回家路上有点冷，座椅加热开得柔和一点。",
            "收到，我会维持较低档位的座椅加热。",
        )
    return (
        f"第{day_index + 1}天通勤路上正常行驶，按平时习惯来。",
        "好的，维持您平时的设置。",
    )


def _preference_templates(copy_index: int, day_label: str) -> Iterable[tuple[str, object, Condition, str]]:
    base_temp = 24 + (copy_index % 3) * 0.5
    yield (
        "ac_temperature",
        base_temp,
        Condition(type="default"),
        f"{day_label} 用户说平时空调 {base_temp:g} 度更舒服。",
    )
    yield (
        "ac_temperature",
        base_temp + 1.0,
        Condition(type="health_state", operator="==", target="sick"),
        f"{day_label} 用户说感冒时空调别太冷，{base_temp + 1.0:g} 度更舒服。",
    )
    yield (
        "ac_temperature",
        base_temp,
        Condition(type="health_state", operator="==", target="recovering"),
        f"{day_label} 用户说恢复期可以回到 {base_temp:g} 度。",
    )
    yield (
        "seat_heating",
        1 + (copy_index % 2),
        Condition(type="default"),
        f"{day_label} 用户说冬天上车默认座椅加热开 {1 + (copy_index % 2)} 档。",
    )
    yield (
        "seat_heating",
        2 + (copy_index % 2),
        Condition(type="weather_state", operator="==", target="rainy"),
        f"{day_label} 用户说下雨天衣服潮，座椅加热想更高一点。",
    )
    yield (
        "music_mode",
        "light",
        Condition(type="default"),
        f"{day_label} 用户说平时开车更喜欢轻音乐。",
    )
    yield (
        "music_mode",
        "silent",
        Condition(type="trip_scene", operator="==", target="family_trip"),
        f"{day_label} 用户说一家人出游时车里想安静一点。",
    )
    yield (
        "music_mode",
        "energizing",
        Condition(type="fatigue_state", operator="==", target="sleepy"),
        f"{day_label} 用户说犯困时想听更提神的音乐。",
    )


def _benchmark_query(
    *,
    query: str,
    lightmem_store: LightMemStore,
    table: PreferenceTable,
    repeat: int,
    warmup: int,
    retrieve_limit: int,
) -> dict[str, object]:
    latest_hits = []
    latest_prefs = []
    for _ in range(warmup):
        latest_hits = lightmem_store.retrieve_records(query, limit=retrieve_limit)
        latest_prefs = [
            match.record.to_policy_payload(
                matched_by=match.matched_by,
                retrieval_score=match.retrieval_score,
                query_score=match.query_score,
            )
            for match in table.find_relevant_matches(
                query_text=query,
                lightmem_hits=latest_hits,
                limit=retrieve_limit,
            )
        ]

    memory_times_ms: list[float] = []
    preference_times_ms: list[float] = []
    total_times_ms: list[float] = []
    for _ in range(repeat):
        total_start = perf_counter()

        start = perf_counter()
        latest_hits = lightmem_store.retrieve_records(query, limit=retrieve_limit)
        memory_times_ms.append((perf_counter() - start) * 1000)

        start = perf_counter()
        latest_prefs = [
            match.record.to_policy_payload(
                matched_by=match.matched_by,
                retrieval_score=match.retrieval_score,
                query_score=match.query_score,
            )
            for match in table.find_relevant_matches(
                query_text=query,
                lightmem_hits=latest_hits,
                limit=retrieve_limit,
            )
        ]
        preference_times_ms.append((perf_counter() - start) * 1000)
        total_times_ms.append((perf_counter() - total_start) * 1000)

    return {
        "memory_times_ms": memory_times_ms,
        "preference_times_ms": preference_times_ms,
        "total_times_ms": total_times_ms,
        "latest_hits": latest_hits,
        "latest_preferences": latest_prefs,
    }


def _format_stats(samples_ms: list[float]) -> str:
    ordered = sorted(samples_ms)
    return (
        f"avg={statistics.fmean(samples_ms):.2f} "
        f"p50={_percentile(ordered, 0.50):.2f} "
        f"p95={_percentile(ordered, 0.95):.2f} "
        f"p99={_percentile(ordered, 0.99):.2f} "
        f"max={ordered[-1]:.2f}"
    )


def _percentile(sorted_samples: list[float], ratio: float) -> float:
    if not sorted_samples:
        return 0.0
    index = max(0, min(len(sorted_samples) - 1, round((len(sorted_samples) - 1) * ratio)))
    return sorted_samples[index]


if __name__ == "__main__":
    main()
