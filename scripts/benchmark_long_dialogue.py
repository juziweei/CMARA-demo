from __future__ import annotations

import argparse
import shutil
import statistics
import sys
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.action.llm_client import OpenAIToolClient
from src.config import DemoConfig
from src.memory.direct_preference_extractor import DirectPreferenceExtractor
from src.memory.lightmem_store import LightMemStore
from src.memory.preference_table import (
    Condition,
    PreferenceMatch,
    PreferenceRecord,
    PreferenceTable,
)


LOOKUP_QUERIES = [
    "一家人出游，孩子在后排睡着了，车里想安静一点。",
    "今天通勤有点犯困，放什么音乐比较合适？",
    "下雨天身上有点潮，座椅加热开几档舒服？",
    "感冒还没好，车里又有点热。",
]

FILLER_SNIPPETS = [
    "路上还要顺便去拿快递、看一下前面高架是不是开始堵了、确认下一个红绿灯后是直接并线还是继续直行。",
    "孩子刚刚在后排讨论学校春游的事，一会儿又问服务区有没有热水、停车位会不会难找、回程要不要绕开商圈。",
    "导航现在提示前面两公里有施工，旁边那条路虽然近一点，但是左转口很碎，真开进去反而可能更慢。",
    "我刚刚还在想等会儿要不要给家里打个电话报平安，不过车里说话有点杂，先把事情一件一件捋顺比较稳。",
    "如果后面开始下大雨，雨刷、除雾、后视镜加热这些都得跟上，不然前挡风玻璃很容易起雾。",
    "等会儿如果看到便利店，提醒我买纸巾和水，别等到上高速以后才发现东西没带齐，到时候又得绕路。",
    "前排这边我还要看一眼手机里的预约时间，免得到地方太早或者太晚，停车场如果满了还得多转一圈。",
    "今天一路上其实杂事很多，路线、停车、天气、孩子状态、到点提醒都堆在一起，说话会比较碎，这种场景才更像真实用车。",
]


@dataclass(frozen=True)
class ExpectedPreference:
    preference: str
    value: Any
    condition: Condition
    cue: str

    def key(self) -> tuple[str, str, str]:
        probe = PreferenceRecord(
            id=-1,
            preference=self.preference,
            value=self.value,
            condition=self.condition,
            status="active",
            source="user_stated",
            evidence=self.cue,
            lightmem_ref=self.cue,
            timestamp="2026-06-03",
        )
        return probe.dedupe_key()


@dataclass(frozen=True)
class DriveCase:
    name: str
    messages: list[dict[str, str]]
    expected: list[ExpectedPreference]
    transcript_chars: int


@dataclass(frozen=True)
class ExtractionStats:
    drive_name: str
    transcript_chars: int
    summarize_ms: float
    raw_items: int
    accepted_items: int
    exact_matches: int
    object_matches: int
    hallucinated: int
    dropped_items: int
    parse_error: str = ""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark long-dialogue extraction quality and lookup latency."
    )
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--dataset", default="long_dialogue")
    parser.add_argument("--days", type=int, default=4)
    parser.add_argument("--drives-per-day", type=int, default=2)
    parser.add_argument(
        "--target-chars",
        type=int,
        default=2200,
        help="Approximate transcript characters per drive.",
    )
    parser.add_argument("--repeat", type=int, default=12)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--retrieve-limit", type=int, default=8)
    parser.add_argument("--show-drives", action="store_true")
    args = parser.parse_args()

    settings, dataset_root = _build_settings(args.dataset)
    if args.reset:
        _reset_dataset(dataset_root)

    client = OpenAIToolClient(
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        api_key=settings.llm_api_key,
    )
    lightmem_store = LightMemStore.from_settings(settings)
    preference_table = PreferenceTable(settings.preferences_path)

    extraction_stats: list[ExtractionStats] = []
    total_expected = 0
    for day_index in range(args.days):
        for drive_index in range(args.drives_per_day):
            drive = _generate_drive_case(
                day_index=day_index,
                drive_index=drive_index,
                target_chars=args.target_chars,
            )
            total_expected += len(drive.expected)
            extraction_stats.append(
                _run_extraction_case(
                    drive=drive,
                    client=client,
                    lightmem_store=lightmem_store,
                    preference_table=preference_table,
                )
            )

    lookup_stats = _run_lookup_benchmark(
        queries=LOOKUP_QUERIES,
        lightmem_store=lightmem_store,
        preference_table=preference_table,
        repeat=args.repeat,
        warmup=args.warmup,
        retrieve_limit=args.retrieve_limit,
    )

    _print_report(
        dataset=args.dataset,
        dataset_root=dataset_root,
        days=args.days,
        drives_per_day=args.drives_per_day,
        total_expected=total_expected,
        active_preferences=preference_table.list_preferences(),
        extraction_stats=extraction_stats,
        lookup_stats=lookup_stats,
        show_drives=args.show_drives,
    )


def _build_settings(dataset_name: str) -> tuple[DemoConfig, Path]:
    root = Path("data/benchmark_long_dialogue") / dataset_name
    settings = replace(DemoConfig())
    settings.preferences_path = root / "preferences.json"
    settings.qdrant_path = root / "qdrant"
    settings.history_db_path = root / "history.db"
    settings.lightmem_collection = f"long_dialogue_{dataset_name}"
    return settings, root


def _reset_dataset(root: Path) -> None:
    if root.exists():
        shutil.rmtree(root)


def _generate_drive_case(
    *,
    day_index: int,
    drive_index: int,
    target_chars: int,
) -> DriveCase:
    profile = (day_index + drive_index) % 4
    base_time = datetime(2026, 6, 1, 8, 0, 0) + timedelta(
        days=day_index,
        hours=drive_index * 4,
    )
    if profile == 0:
        name = f"day{day_index + 1:02d}_family_sick_{drive_index + 1:02d}"
        expected = [
            ExpectedPreference(
                preference="ac_temperature",
                value=26.0 + (day_index % 2) * 0.5,
                condition=Condition(type="health_state", operator="==", target="sick"),
                cue=f"如果我感冒还没完全好，空调调到 {26.0 + (day_index % 2) * 0.5:g} 度会舒服一些。",
            ),
            ExpectedPreference(
                preference="music_mode",
                value="silent",
                condition=Condition(
                    type="trip_scene",
                    operator="==",
                    target="family_trip",
                ),
                cue="一家人一起出门而且孩子在车上睡觉时，我一般不想车里太吵，先别主动放音乐。",
            ),
        ]
        topic_lines = [
            "今天是周末一家人一起出门，后排两个孩子刚刚还在抢零食，结果上车没多久就都安静下来了。",
            expected[0].cue,
            "导航说前面那段高架有点慢，不过如果现在切出去又会多两个红绿灯，我还在犹豫要不要换线。",
            expected[1].cue,
        ]
    elif profile == 1:
        name = f"day{day_index + 1:02d}_sleepy_commute_{drive_index + 1:02d}"
        expected = [
            ExpectedPreference(
                preference="music_mode",
                value="energizing",
                condition=Condition(
                    type="fatigue_state",
                    operator="==",
                    target="sleepy",
                ),
                cue="早高峰如果我明显犯困，就放一点提神的音乐，别太炸，但要能让我清醒。",
            ),
            ExpectedPreference(
                preference="ac_temperature",
                value=24.0 + (drive_index % 2) * 0.5,
                condition=Condition(type="default"),
                cue=f"平时通勤空调大概 {24.0 + (drive_index % 2) * 0.5:g} 度我会觉得比较顺手。",
            ),
        ]
        topic_lines = [
            "今天早上出门有点晚，我一边听导航一边还在想会议纪要到底发没发出去，脑子有点钝。",
            expected[0].cue,
            "前面这段路最烦的是你以为它在走，其实每个路口都要踩一脚刹车，特别消耗注意力。",
            expected[1].cue,
        ]
    elif profile == 2:
        name = f"day{day_index + 1:02d}_rainy_winter_{drive_index + 1:02d}"
        expected = [
            ExpectedPreference(
                preference="seat_heating",
                value=2 + ((day_index + drive_index) % 2),
                condition=Condition(
                    type="weather_state",
                    operator="==",
                    target="rainy",
                ),
                cue=f"下雨天衣服有点潮的时候，座椅加热我会想开到 {2 + ((day_index + drive_index) % 2)} 档。",
            ),
            ExpectedPreference(
                preference="music_mode",
                value="light",
                condition=Condition(type="default"),
                cue="如果不是很困也不是带孩子，我平时还是更习惯轻一点的音乐，不要太吵。",
            ),
        ]
        topic_lines = [
            "今天雨一直没停，鞋底带进来的水把脚垫都弄湿了，前挡风玻璃也总想起雾。",
            expected[0].cue,
            "我还得盯着路边那些突然窜出来的电动车，遇到这种天气注意力基本都耗在防御驾驶上。",
            expected[1].cue,
        ]
    else:
        name = f"day{day_index + 1:02d}_family_default_{drive_index + 1:02d}"
        expected = [
            ExpectedPreference(
                preference="ac_temperature",
                value=24.5 + (day_index % 3) * 0.5,
                condition=Condition(type="default"),
                cue=f"带家人长途出去玩的时候，空调大概 {24.5 + (day_index % 3) * 0.5:g} 度我觉得最舒服。",
            ),
            ExpectedPreference(
                preference="music_mode",
                value="light",
                condition=Condition(type="default"),
                cue="如果大家都醒着而且路况平稳，就放点轻音乐，别把车里气氛弄得太紧张。",
            ),
        ]
        topic_lines = [
            "今天这一趟主要是去郊区，路不会特别堵，但停车和吃饭要提前想好，不然带着一家人临时找地方会很乱。",
            expected[0].cue,
            "后排现在情绪还不错，不过我估计等会儿时间一长就会开始问什么时候到，所以节奏最好稳一点。",
            expected[1].cue,
        ]

    messages: list[dict[str, str]] = []
    turn_count = 10
    min_chars_per_message = max(120, target_chars // turn_count)
    for turn_index in range(turn_count):
        speaker = "user" if turn_index % 2 == 0 else "assistant"
        if speaker == "user":
            base = topic_lines[(turn_index // 2) % len(topic_lines)]
            content = _pad_text(
                base=base,
                min_chars=min_chars_per_message,
                offset=day_index + drive_index + turn_index,
            )
        else:
            content = _pad_text(
                base=(
                    "收到，我先按您现在说的情况记着，路线、停车、提醒、车内环境这些我都会一边听一边跟进。"
                ),
                min_chars=min_chars_per_message,
                offset=day_index * 7 + drive_index * 3 + turn_index,
            )
        messages.append(
            {
                "role": speaker,
                "content": content,
                "time_stamp": (
                    base_time + timedelta(minutes=turn_index * 3)
                ).isoformat(timespec="seconds"),
            }
        )

    transcript_chars = sum(len(message["content"]) for message in messages)
    return DriveCase(
        name=name,
        messages=messages,
        expected=expected,
        transcript_chars=transcript_chars,
    )


def _pad_text(*, base: str, min_chars: int, offset: int) -> str:
    text = base.strip()
    index = offset
    while len(text) < min_chars:
        text += " " + FILLER_SNIPPETS[index % len(FILLER_SNIPPETS)]
        index += 1
    return text


def _run_extraction_case(
    *,
    drive: DriveCase,
    client: OpenAIToolClient,
    lightmem_store: LightMemStore,
    preference_table: PreferenceTable,
) -> ExtractionStats:
    start = perf_counter()
    lightmem_store.offline_extract(drive.messages)
    extractor = DirectPreferenceExtractor(llm_client=client)
    result = extractor.extract(drive.messages)
    parse_error = "parse_failed" if result.parse_failed else ""
    raw_items = result.raw_items
    accepted = result.preferences

    accepted_keys: set[tuple[str, str, str]] = set()
    accepted_objects: list[str] = []
    for item in accepted:
        record, _ = preference_table.upsert_preference(
            preference=item.preference,
            value=item.value,
            condition=item.condition,
            source="offline_summary",
            evidence=item.evidence,
            lightmem_ref=item.evidence,
        )
        accepted_keys.add(record.dedupe_key())
        accepted_objects.append(record.preference)

    expected_keys = {item.key() for item in drive.expected}
    expected_objects = [item.preference for item in drive.expected]
    exact_matches = len(expected_keys & accepted_keys)
    object_matches = sum(
        1 for preference in expected_objects if preference in accepted_objects
    )
    summarize_ms = (perf_counter() - start) * 1000
    hallucinated = max(0, len(accepted_keys - expected_keys))
    dropped_items = max(0, len(raw_items) - len(accepted))
    return ExtractionStats(
        drive_name=drive.name,
        transcript_chars=drive.transcript_chars,
        summarize_ms=summarize_ms,
        raw_items=len(raw_items),
        accepted_items=len(accepted),
        exact_matches=exact_matches,
        object_matches=object_matches,
        hallucinated=hallucinated,
        dropped_items=dropped_items,
        parse_error=parse_error,
    )


def _run_lookup_benchmark(
    *,
    queries: Sequence[str],
    lightmem_store: LightMemStore,
    preference_table: PreferenceTable,
    repeat: int,
    warmup: int,
    retrieve_limit: int,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for query in queries:
        latest_hits = []
        latest_prefs: list[PreferenceMatch] = []
        for _ in range(warmup):
            latest_hits = lightmem_store.retrieve_records(query, limit=retrieve_limit)
            latest_prefs = preference_table.find_relevant_matches(
                query_text=query,
                lightmem_hits=latest_hits,
                limit=retrieve_limit,
            )

        memory_ms: list[float] = []
        pref_ms: list[float] = []
        total_ms: list[float] = []
        for _ in range(repeat):
            total_start = perf_counter()

            start = perf_counter()
            latest_hits = lightmem_store.retrieve_records(query, limit=retrieve_limit)
            memory_ms.append((perf_counter() - start) * 1000)

            start = perf_counter()
            latest_prefs = preference_table.find_relevant_matches(
                query_text=query,
                lightmem_hits=latest_hits,
                limit=retrieve_limit,
            )
            pref_ms.append((perf_counter() - start) * 1000)
            total_ms.append((perf_counter() - total_start) * 1000)

        results.append(
            {
                "query": query,
                "memory_ms": memory_ms,
                "pref_ms": pref_ms,
                "total_ms": total_ms,
                "latest_hits": latest_hits,
                "latest_prefs": latest_prefs,
            }
        )
    return results


def _print_report(
    *,
    dataset: str,
    dataset_root: Path,
    days: int,
    drives_per_day: int,
    total_expected: int,
    active_preferences: list[PreferenceRecord],
    extraction_stats: list[ExtractionStats],
    lookup_stats: list[dict[str, Any]],
    show_drives: bool,
) -> None:
    summarize_ms = [item.summarize_ms for item in extraction_stats]
    total_chars = sum(item.transcript_chars for item in extraction_stats)
    raw_items = sum(item.raw_items for item in extraction_stats)
    accepted_items = sum(item.accepted_items for item in extraction_stats)
    exact_matches = sum(item.exact_matches for item in extraction_stats)
    object_matches = sum(item.object_matches for item in extraction_stats)
    hallucinated = sum(item.hallucinated for item in extraction_stats)
    dropped_items = sum(item.dropped_items for item in extraction_stats)
    parse_failures = [item for item in extraction_stats if item.parse_error]

    print("=== Long Dialogue Benchmark ===")
    print(f"dataset={dataset}")
    print(f"storage_root={dataset_root}")
    print(f"days={days}")
    print(f"drives_per_day={drives_per_day}")
    print(f"drives_total={len(extraction_stats)}")
    print(f"dialogue_chars_total={total_chars}")
    print(f"dialogue_chars_avg={total_chars / max(1, len(extraction_stats)):.0f}")
    print(f"expected_preferences={total_expected}")
    print(f"raw_summary_items={raw_items}")
    print(f"accepted_structured_items={accepted_items}")
    print(f"active_structured_preferences={len(active_preferences)}")
    print(f"exact_match_rate={exact_matches / max(1, total_expected):.2%}")
    print(f"object_match_rate={object_matches / max(1, total_expected):.2%}")
    print(f"hallucinated_items={hallucinated}")
    print(f"dropped_items={dropped_items}")
    print(f"parse_failures={len(parse_failures)}")
    print(
        "summarize_ms "
        + _format_stats(summarize_ms)
    )
    print("-" * 60)

    if show_drives:
        for item in extraction_stats:
            print(
                f"drive={item.drive_name} chars={item.transcript_chars} "
                f"summarize_ms={item.summarize_ms:.2f} raw={item.raw_items} "
                f"accepted={item.accepted_items} exact={item.exact_matches} "
                f"object={item.object_matches} hallucinated={item.hallucinated} "
                f"dropped={item.dropped_items} parse_error={'yes' if item.parse_error else 'no'}"
            )
        print("-" * 60)

    for item in parse_failures[:3]:
        print(f"parse_failure={item.drive_name} detail={item.parse_error}")
    if parse_failures:
        print("-" * 60)

    for lookup in lookup_stats:
        print(f"query={lookup['query']}")
        print("  memory_ms  " + _format_stats(lookup["memory_ms"]))
        print("  pref_ms    " + _format_stats(lookup["pref_ms"]))
        print("  total_ms   " + _format_stats(lookup["total_ms"]))
        print(
            f"  latest_hits={len(lookup['latest_hits'])} "
            f"latest_prefs={len(lookup['latest_prefs'])}"
        )
        print("-" * 60)


def _format_stats(values: Sequence[float]) -> str:
    ordered = sorted(values)
    return (
        f"avg={statistics.fmean(values):.2f} "
        f"p50={_percentile(ordered, 0.50):.2f} "
        f"p95={_percentile(ordered, 0.95):.2f} "
        f"p99={_percentile(ordered, 0.99):.2f} "
        f"max={ordered[-1]:.2f}"
    )


def _percentile(sorted_values: Sequence[float], ratio: float) -> float:
    if not sorted_values:
        return 0.0
    index = max(
        0,
        min(len(sorted_values) - 1, round((len(sorted_values) - 1) * ratio)),
    )
    return sorted_values[index]


if __name__ == "__main__":
    main()
