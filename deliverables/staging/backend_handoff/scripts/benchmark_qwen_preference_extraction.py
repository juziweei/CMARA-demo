from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.action.llm_client import OpenAIToolClient
from src.config import DemoConfig
from src.memory.direct_preference_extractor import (
    DirectPreferenceExtractor,
    ExtractedPreference,
)
from src.memory.preference_table import Condition

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

    def dedupe_key(self) -> tuple[str, str, str]:
        return (
            self.preference,
            json.dumps(self.condition.to_dict(), ensure_ascii=False, sort_keys=True),
            json.dumps(self.value, ensure_ascii=False, sort_keys=True),
        )


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
    extract_ms: float
    raw_items: int
    normalized_items: int
    exact_matches: int
    object_matches: int
    parse_failed: bool
    retry_used: bool
    extracted: list[ExtractedPreference]
    missed: list[ExpectedPreference]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark direct Qwen preference extraction on the long-dialogue dataset."
    )
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--drives-per-day", type=int, default=2)
    parser.add_argument("--target-chars", type=int, default=2200)
    parser.add_argument("--show-drives", action="store_true")
    parser.add_argument("--show-items", type=int, default=3)
    args = parser.parse_args()

    settings = DemoConfig()
    client = OpenAIToolClient(
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        api_key=settings.llm_api_key,
    )
    extractor = DirectPreferenceExtractor(llm_client=client)

    stats: list[ExtractionStats] = []
    total_expected = 0
    for day_index in range(args.days):
        for drive_index in range(args.drives_per_day):
            drive = _generate_drive_case(
                day_index=day_index,
                drive_index=drive_index,
                target_chars=args.target_chars,
            )
            total_expected += len(drive.expected)
            stats.append(_run_case(drive=drive, extractor=extractor))

    _print_report(
        stats=stats,
        total_expected=total_expected,
        days=args.days,
        drives_per_day=args.drives_per_day,
        show_drives=args.show_drives,
        show_items=max(0, args.show_items),
    )


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


def _run_case(
    *,
    drive: DriveCase,
    extractor: DirectPreferenceExtractor,
) -> ExtractionStats:
    start = perf_counter()
    result = extractor.extract(drive.messages)
    extract_ms = (perf_counter() - start) * 1000

    expected_keys = {item.dedupe_key() for item in drive.expected}
    actual_keys = {item.dedupe_key() for item in result.preferences}
    expected_objects = [item.preference for item in drive.expected]
    actual_objects = [item.preference for item in result.preferences]
    exact_matches = len(expected_keys & actual_keys)
    object_matches = sum(
        1 for preference in expected_objects if preference in actual_objects
    )
    missed = [item for item in drive.expected if item.dedupe_key() not in actual_keys]

    return ExtractionStats(
        drive_name=drive.name,
        transcript_chars=drive.transcript_chars,
        extract_ms=extract_ms,
        raw_items=len(result.raw_items),
        normalized_items=len(result.preferences),
        exact_matches=exact_matches,
        object_matches=object_matches,
        parse_failed=result.parse_failed,
        retry_used=result.repaired_response is not None,
        extracted=result.preferences,
        missed=missed,
    )


def _print_report(
    *,
    stats: list[ExtractionStats],
    total_expected: int,
    days: int,
    drives_per_day: int,
    show_drives: bool,
    show_items: int,
) -> None:
    extract_times = [item.extract_ms for item in stats]
    raw_items = sum(item.raw_items for item in stats)
    normalized_items = sum(item.normalized_items for item in stats)
    exact_matches = sum(item.exact_matches for item in stats)
    object_matches = sum(item.object_matches for item in stats)
    parse_failures = sum(1 for item in stats if item.parse_failed)
    retries = sum(1 for item in stats if item.retry_used)

    print("=== Direct Qwen Preference Extraction ===")
    print(f"days={days}")
    print(f"drives_per_day={drives_per_day}")
    print(f"drives_total={len(stats)}")
    print(f"expected_preferences_total={total_expected}")
    print(f"raw_items={raw_items}")
    print(f"normalized_items={normalized_items}")
    print(f"exact_match_rate={exact_matches / max(1, total_expected):.2%}")
    print(f"object_match_rate={object_matches / max(1, total_expected):.2%}")
    print(f"parse_failures={parse_failures}")
    print(f"retry_used={retries}")
    print(
        "extract_ms "
        + _format_stats(extract_times)
    )
    print("-" * 72)

    sample_extracted = []
    sample_missed = []
    for item in stats:
        for extracted in item.extracted:
            sample_extracted.append(extracted)
        for missed in item.missed:
            sample_missed.append(missed)

    for extracted in sample_extracted[:show_items]:
        print(
            "extract> "
            f"{extracted.preference}={extracted.value} | "
            f"{json.dumps(extracted.condition.to_dict(), ensure_ascii=False)} | "
            f"{extracted.evidence}"
        )
    for missed in sample_missed[:show_items]:
        print(
            "miss> "
            f"{missed.preference}={missed.value} | "
            f"{json.dumps(missed.condition.to_dict(), ensure_ascii=False)} | "
            f"{missed.cue}"
        )

    if show_drives:
        print("-" * 72)
        for item in stats:
            print(
                f"drive={item.drive_name} chars={item.transcript_chars} "
                f"extract_ms={item.extract_ms:.2f} raw={item.raw_items} "
                f"normalized={item.normalized_items} exact={item.exact_matches} "
                f"object={item.object_matches} retry={'yes' if item.retry_used else 'no'} "
                f"parse_failed={'yes' if item.parse_failed else 'no'}"
            )


def _format_stats(values: list[float]) -> str:
    if not values:
        return "count=0"
    values = sorted(values)
    avg = sum(values) / len(values)
    p50 = values[len(values) // 2]
    p95 = values[min(len(values) - 1, int(len(values) * 0.95))]
    return (
        f"count={len(values)} avg={avg:.2f} "
        f"p50={p50:.2f} p95={p95:.2f} max={values[-1]:.2f}"
    )


if __name__ == "__main__":
    main()
