from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import DemoConfig
from src.memory.lightmem_store import LightMemStore
from src.memory.preference_table import Condition


DOMAIN_MARKERS = (
    "空调",
    "温度",
    "ac",
    "air conditioning",
    "air conditioner",
    "music",
    "音乐",
    "轻音乐",
    "安静",
    "提神",
    "座椅加热",
    "seat heating",
    "seat heater",
)

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
class Combo:
    name: str
    extraction_mode: str
    pre_compress: bool


@dataclass(frozen=True)
class ExpectedPreference:
    preference: str
    value: Any
    condition: Condition
    cue: str


@dataclass(frozen=True)
class DriveCase:
    name: str
    messages: list[dict[str, str]]
    expected: list[ExpectedPreference]
    transcript_chars: int


@dataclass(frozen=True)
class DriveResult:
    drive_name: str
    transcript_chars: int
    expected_total: int
    expected_hits: int
    factual_entries: int
    relational_entries: int
    domain_candidate_facts: int
    json_failures: int
    matched_facts: list[str]
    missed_cues: list[str]


COMBOS = (
    Combo("flat_compress_on", extraction_mode="flat", pre_compress=True),
    Combo("flat_compress_off", extraction_mode="flat", pre_compress=False),
    Combo("event_compress_on", extraction_mode="event", pre_compress=True),
    Combo("event_compress_off", extraction_mode="event", pre_compress=False),
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="A/B benchmark for LightMem raw preference-fact extraction."
    )
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--dataset", default="ab")
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--drives-per-day", type=int, default=2)
    parser.add_argument("--target-chars", type=int, default=2200)
    parser.add_argument("--show-drives", action="store_true")
    parser.add_argument("--show-facts", type=int, default=2)
    args = parser.parse_args()

    _prepare_lightmem_runtime()
    combo_results: list[tuple[Combo, list[DriveResult], Path]] = []
    total_expected = args.days * args.drives_per_day * 2

    for combo in COMBOS:
        settings, dataset_root = _build_settings(args.dataset, combo)
        if args.reset:
            _reset_dataset(dataset_root)
        lightmem_store = LightMemStore.from_settings(settings)
        drive_results: list[DriveResult] = []
        for day_index in range(args.days):
            for drive_index in range(args.drives_per_day):
                drive = _generate_drive_case(
                    day_index=day_index,
                    drive_index=drive_index,
                    target_chars=args.target_chars,
                )
                drive_results.append(_run_drive(drive, lightmem_store))
        combo_results.append((combo, drive_results, dataset_root))

    _print_report(
        combo_results=combo_results,
        total_expected=total_expected,
        days=args.days,
        drives_per_day=args.drives_per_day,
        show_drives=args.show_drives,
        show_facts=max(0, args.show_facts),
    )


def _build_settings(dataset_name: str, combo: Combo) -> tuple[DemoConfig, Path]:
    root = Path("data/benchmark_lightmem_fact_ab") / dataset_name / combo.name
    settings = replace(DemoConfig())
    settings.preferences_path = root / "preferences.json"
    settings.qdrant_path = root / "qdrant"
    settings.history_db_path = root / "history.db"
    settings.lightmem_collection = f"fact_ab_{dataset_name}_{combo.name}"
    settings.lightmem_extraction_mode = combo.extraction_mode
    settings.lightmem_pre_compress = combo.pre_compress
    return settings, root


def _prepare_lightmem_runtime() -> None:
    from lightmem.memory.lightmem import LightMemory

    if not hasattr(LightMemory, "compressor"):
        LightMemory.compressor = None


def _reset_dataset(root: Path) -> None:
    if root.exists():
        shutil.rmtree(root)


def _run_drive(drive: Any, lightmem_store: LightMemStore) -> DriveResult:
    result = lightmem_store.offline_extract(drive.messages)
    factual_entries, relational_entries, json_failures = _parse_add_output_prompts(
        result.get("add_output_prompt", [])
    )
    factual_entries = _dedupe_preserve_order(factual_entries)
    relational_entries = _dedupe_preserve_order(relational_entries)
    domain_candidate_facts = [
        fact for fact in factual_entries if _is_domain_fact(fact)
    ]

    matched_facts: list[str] = []
    missed_cues: list[str] = []
    for expected in drive.expected:
        matched = _find_match(expected, factual_entries)
        if matched is None:
            missed_cues.append(expected.cue)
        else:
            matched_facts.append(matched)

    return DriveResult(
        drive_name=drive.name,
        transcript_chars=drive.transcript_chars,
        expected_total=len(drive.expected),
        expected_hits=len(matched_facts),
        factual_entries=len(factual_entries),
        relational_entries=len(relational_entries),
        domain_candidate_facts=len(domain_candidate_facts),
        json_failures=json_failures,
        matched_facts=_dedupe_preserve_order(matched_facts),
        missed_cues=missed_cues,
    )


def _parse_add_output_prompts(outputs: Iterable[str]) -> tuple[list[str], list[str], int]:
    factual_entries: list[str] = []
    relational_entries: list[str] = []
    json_failures = 0

    for output in outputs:
        if not isinstance(output, str) or not output.strip():
            continue
        stripped = output.strip()
        if stripped.startswith("Factual:") and "\nRelational:" in stripped:
            factual_raw, relational_raw = stripped.split("\nRelational:", 1)
            factual_items, factual_failed = _parse_payload(
                _strip_prefix(factual_raw, "Factual:").strip()
            )
            relational_items, relational_failed = _parse_payload(relational_raw.strip())
            json_failures += int(factual_failed) + int(relational_failed)
            factual_entries.extend(_extract_text_entries(factual_items, "fact"))
            relational_entries.extend(_extract_text_entries(relational_items, "relation"))
            continue

        items, failed = _parse_payload(stripped)
        json_failures += int(failed)
        factual_entries.extend(_extract_text_entries(items, "fact"))
        relational_entries.extend(_extract_text_entries(items, "relation"))

    return factual_entries, relational_entries, json_failures


def _parse_payload(payload: str) -> tuple[list[dict[str, Any]], bool]:
    cleaned = _strip_code_fence(payload)
    if not cleaned or cleaned == "N/A":
        return [], False
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return [], True

    if isinstance(parsed, dict) and isinstance(parsed.get("data"), list):
        return [item for item in parsed["data"] if isinstance(item, dict)], False
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)], False
    return [], False


def _strip_code_fence(text: str) -> str:
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text.strip())
    if match:
        return match.group(1).strip()
    return text.strip()


def _strip_prefix(text: str, prefix: str) -> str:
    if text.startswith(prefix):
        return text[len(prefix) :]
    return text


def _extract_text_entries(
    items: list[dict[str, Any]], key: str
) -> list[str]:
    values: list[str] = []
    for item in items:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
    return values


def _find_match(expected: ExpectedPreference, factual_entries: list[str]) -> str | None:
    for fact in factual_entries:
        if _matches_expected_fact(expected, fact):
            return fact
    return None


def _matches_expected_fact(expected: ExpectedPreference, fact: str) -> bool:
    text = fact.lower()
    if not _condition_matches(expected, text):
        return False

    if expected.preference == "ac_temperature":
        return _contains_any(
            text,
            ("空调", "ac", "air conditioning", "air conditioner", "温度", "temperature"),
        ) and _matches_numeric_value(text, expected.value)

    if expected.preference == "seat_heating":
        return _contains_any(
            text,
            ("座椅加热", "seat heating", "seat heater"),
        ) and _matches_numeric_value(text, expected.value)

    if expected.preference == "music_mode":
        value_markers = _music_value_markers(str(expected.value))
        object_markers = ("音乐", "music", *value_markers)
        return _contains_any(text, object_markers) and _contains_any(text, value_markers)

    return False


def _condition_matches(expected: ExpectedPreference, text: str) -> bool:
    condition = expected.condition
    if condition.type == "default":
        return True
    if condition.type == "health_state":
        return _contains_any(
            text,
            ("感冒", "生病", "没好", "恢复", "cold", "sick", "ill", "recovering", "recovery"),
        )
    if condition.type == "fatigue_state":
        return _contains_any(
            text,
            ("犯困", "困", "瞌睡", "sleepy", "drowsy", "tired"),
        )
    if condition.type == "weather_state":
        return _contains_any(
            text,
            ("下雨", "雨天", "潮", "rain", "rainy", "wet", "damp"),
        )
    if condition.type == "trip_scene":
        return _contains_any(
            text,
            ("一家人", "家人", "孩子", "后排", "family", "children", "kids", "child"),
        )
    return False


def _matches_numeric_value(text: str, value: Any) -> bool:
    variants = {f"{value:g}"}
    if isinstance(value, float):
        variants.add(f"{value:.1f}")
    return any(variant in text for variant in variants)


def _music_value_markers(value: str) -> tuple[str, ...]:
    if value == "silent":
        return ("安静", "别放音乐", "不放音乐", "不要放音乐", "silent", "quiet", "no music")
    if value == "light":
        return ("轻音乐", "轻一点", "不要太吵", "light music", "soft music", "gentle")
    if value == "energizing":
        return ("提神", "清醒", "energizing", "energetic", "wake up")
    return (value.lower(),)


def _is_domain_fact(fact: str) -> bool:
    return _contains_any(fact.lower(), DOMAIN_MARKERS)


def _contains_any(text: str, markers: Iterable[str]) -> bool:
    return any(marker and marker.lower() in text for marker in markers)


def _dedupe_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _print_report(
    *,
    combo_results: list[tuple[Combo, list[DriveResult], Path]],
    total_expected: int,
    days: int,
    drives_per_day: int,
    show_drives: bool,
    show_facts: int,
) -> None:
    print("=== LightMem Raw Fact A/B ===")
    print(f"days={days}")
    print(f"drives_per_day={drives_per_day}")
    print(f"drives_total={days * drives_per_day}")
    print(f"expected_preferences_total={total_expected}")
    print("-" * 72)

    ranked = sorted(
        combo_results,
        key=lambda item: (
            -sum(result.expected_hits for result in item[1]),
            sum(result.json_failures for result in item[1]),
            -sum(result.domain_candidate_facts for result in item[1]),
        ),
    )

    for rank, (combo, results, dataset_root) in enumerate(ranked, start=1):
        expected_hits = sum(result.expected_hits for result in results)
        factual_entries = sum(result.factual_entries for result in results)
        relational_entries = sum(result.relational_entries for result in results)
        domain_candidate_facts = sum(result.domain_candidate_facts for result in results)
        json_failures = sum(result.json_failures for result in results)
        full_hit_drives = sum(
            1 for result in results if result.expected_hits == result.expected_total
        )
        matched_facts = _dedupe_preserve_order(
            fact for result in results for fact in result.matched_facts
        )
        missed_cues = [
            cue for result in results for cue in result.missed_cues
        ]
        precision = len(matched_facts) / max(1, domain_candidate_facts)

        print(f"[{rank}] combo={combo.name}")
        print(
            f"  extraction_mode={combo.extraction_mode} pre_compress={combo.pre_compress}"
        )
        print(f"  storage_root={dataset_root}")
        print(
            f"  expected_hits={expected_hits}/{total_expected} "
            f"({expected_hits / max(1, total_expected):.2%})"
        )
        print(f"  full_hit_drives={full_hit_drives}/{len(results)}")
        print(
            f"  factual_entries={factual_entries} relational_entries={relational_entries}"
        )
        print(
            f"  domain_candidate_facts={domain_candidate_facts} "
            f"matched_unique_facts={len(matched_facts)} precision={precision:.2%}"
        )
        print(f"  json_failures={json_failures}")
        if matched_facts:
            for fact in matched_facts[:show_facts]:
                print(f"  match> {fact}")
        if missed_cues:
            for cue in missed_cues[:show_facts]:
                print(f"  miss> {cue}")
        if show_drives:
            for result in results:
                print(
                    f"  drive={result.drive_name} chars={result.transcript_chars} "
                    f"hits={result.expected_hits}/{result.expected_total} "
                    f"facts={result.factual_entries} relations={result.relational_entries} "
                    f"domain_facts={result.domain_candidate_facts} json_failures={result.json_failures}"
                )
        print("-" * 72)


if __name__ == "__main__":
    main()
