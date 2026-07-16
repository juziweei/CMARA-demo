from __future__ import annotations

import copy
from typing import Any

SCENARIO_ALIASES = {
    "family_trip": "family_coastal_trip",
}


SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "family_coastal_trip",
        "title": "Family Coastal Trip",
        "subtitle": "Quiet cabin, sleeping child, hot-weather reuse, and a memory summary.",
        "demo_goal": (
            "Show a family trip with a quiet-cabin preference, a hot-weather ASK, "
            "clarification learning, and a reuse turn on the next outing."
        ),
        "memory_dimensions": [
            "family_trip",
            "child_sleep",
            "music",
            "temperature",
            "health_state",
        ],
        "visual_focus": [
            "Memory Timeline",
            "Decision Flow",
            "Clarification Learning",
        ],
        "seed_preferences": [
            {
                "preference": "ac_temperature",
                "value": 24,
                "condition": {"type": "default"},
                "source": "user_stated",
                "evidence": "When our family travels, 24 C is the most comfortable cabin temperature.",
            },
            {
                "preference": "ac_temperature",
                "value": 25.5,
                "condition": {
                    "type": "health_state",
                    "operator": "==",
                    "target": "sick",
                },
                "source": "user_stated",
                "evidence": "If I am still sick on a family trip, 25.5 C feels better than a cold cabin.",
            },
        ],
        "script": [
            {
                "kind": "turn",
                "label": "Trip context",
                "text": (
                    "We are leaving for the coast this Saturday with my wife and our daughter. "
                    "She usually falls asleep after twenty minutes, so keep the cabin quiet, "
                    "keep the music off while she sleeps, and only interrupt with voice prompts "
                    "when something important changes."
                ),
            },
            {
                "kind": "turn",
                "label": "Family rhythm",
                "text": (
                    "If traffic stays normal, I want the drive to feel peaceful enough that nobody "
                    "needs to talk over the cabin. The main thing is that she keeps sleeping and "
                    "the trip does not feel noisy or rushed."
                ),
            },
            {
                "kind": "summary",
                "label": "Offline summary",
                "text": (
                    "Summarize the day-one family-trip conversation into reusable preferences."
                ),
            },
            {
                "kind": "turn",
                "label": "Hot weather",
                "text": "The cabin feels hot now.",
            },
            {
                "kind": "clarification",
                "label": "Clarification answer",
                "text": "I feel much better today, basically recovered.",
            },
            {
                "kind": "turn",
                "label": "Reuse",
                "text": (
                    "We are doing the same family trip again next weekend, and the cabin feels hot already."
                ),
            },
        ],
    },
    {
        "id": "morning_commute_time_pressure",
        "title": "Morning Commute Under Time Pressure",
        "subtitle": "Seat heating, passenger health ambiguity, and a learned recovery state.",
        "demo_goal": (
            "Show a rushed commute where the system learns whether to keep the seat heating "
            "low or warm up the cabin for a passenger who may still be recovering."
        ),
        "memory_dimensions": [
            "commute",
            "seat_heating",
            "passenger_health_state",
            "time_pressure",
        ],
        "visual_focus": [
            "ASK / ACT Gate",
            "Passenger State",
            "Reuse After Learning",
        ],
        "seed_preferences": [
            {
                "preference": "seat_heating",
                "value": 1,
                "condition": {"type": "default"},
                "source": "user_stated",
                "evidence": "On rushed weekday mornings, level 1 is warm enough without making me sleepy.",
            },
            {
                "preference": "seat_heating",
                "value": 3,
                "condition": {
                    "type": "passenger_health_state",
                    "operator": "==",
                    "target": "sick",
                },
                "source": "user_stated",
                "evidence": "If my father is still sick, he prefers a warmer seat on the morning commute.",
            },
        ],
        "script": [
            {
                "kind": "turn",
                "label": "Weekday routine",
                "text": (
                    "On rushed weekday mornings, I keep the seat heating at level 1 because anything warmer "
                    "makes me feel sleepy before the meeting starts, and I need my head clear before the commute begins."
                ),
            },
            {
                "kind": "turn",
                "label": "Passenger context",
                "text": (
                    "My father is riding with me today, and he says the trip should stay comfortable, but he will not say "
                    "whether he is actually unwell or just tired from the early train."
                ),
            },
            {
                "kind": "summary",
                "label": "Offline summary",
                "text": "Summarize the morning-commute conversation into a compact preference note.",
            },
            {
                "kind": "turn",
                "label": "Chilly cabin",
                "text": "The cabin feels chilly now.",
            },
            {
                "kind": "clarification",
                "label": "Clarification answer",
                "text": "He is still recovering from a cold, but he does not want me to fuss over it.",
            },
            {
                "kind": "turn",
                "label": "Reuse",
                "text": (
                    "I am taking him home again next week, and the cabin feels chilly now."
                ),
            },
        ],
    },
    {
        "id": "elderly_passenger_comfort",
        "title": "Elderly Passenger Comfort",
        "subtitle": "A clinic run that resolves a passenger-health ambiguity and then reuses it.",
        "demo_goal": (
            "Show how a gentle cabin preference for an older passenger turns into a learned "
            "health-aware comfort rule that can be reused later."
        ),
        "memory_dimensions": [
            "passenger_health_state",
            "temperature",
            "gentle_comfort",
            "clinic_run",
        ],
        "visual_focus": [
            "Memory Source",
            "Condition Activation",
            "Learned Recovery Rule",
        ],
        "seed_preferences": [
            {
                "preference": "ac_temperature",
                "value": 23,
                "condition": {"type": "default"},
                "source": "user_stated",
                "evidence": "On quiet local drives, 23 C keeps the cabin gentle without feeling cold.",
            },
            {
                "preference": "ac_temperature",
                "value": 25.5,
                "condition": {
                    "type": "passenger_health_state",
                    "operator": "==",
                    "target": "sick",
                },
                "source": "user_stated",
                "evidence": "If my mother is still sick, she prefers the cabin a little warmer.",
            },
        ],
        "script": [
            {
                "kind": "turn",
                "label": "Clinic drive",
                "text": (
                    "I am taking my mother to the clinic across town, and I want the cabin to feel gentle because she has had "
                    "a rough morning and does not want the air blasting at her face."
                ),
            },
            {
                "kind": "turn",
                "label": "Comfort note",
                "text": (
                    "If there is a choice, I would rather keep the ride smooth and conservative than make her uncomfortable just "
                    "because I am in a hurry."
                ),
            },
            {
                "kind": "summary",
                "label": "Offline summary",
                "text": "Summarize the clinic drive conversation into reusable comfort preferences.",
            },
            {
                "kind": "turn",
                "label": "Too warm",
                "text": "It feels too warm in here now.",
            },
            {
                "kind": "clarification",
                "label": "Clarification answer",
                "text": "She is much better today, just a little sensitive after a rough night.",
            },
            {
                "kind": "turn",
                "label": "Reuse",
                "text": (
                    "Next week when I drive her again, it feels too warm in here."
                ),
            },
        ],
    },
    {
        "id": "quiet_work_call_mode",
        "title": "Quiet Work Call Mode",
        "subtitle": "Music mode, call privacy, and a choice between silence and energy.",
        "demo_goal": (
            "Show how the assistant handles a client-call scenario where the user wants quiet audio, "
            "then learns a reusable silent mode after clarification."
        ),
        "memory_dimensions": [
            "work_call",
            "music_mode",
            "alertness",
            "silence",
        ],
        "visual_focus": [
            "Decision Trace",
            "Audio Preference",
            "Clarification Learning",
        ],
        "seed_preferences": [
            {
                "preference": "music_mode",
                "value": "light",
                "condition": {"type": "default"},
                "source": "user_stated",
                "evidence": "On ordinary drives, a little light music feels comfortable.",
            },
            {
                "preference": "music_mode",
                "value": "energizing",
                "condition": {
                    "type": "fatigue_state",
                    "operator": "==",
                    "target": "sleepy",
                },
                "source": "user_stated",
                "evidence": "When I am sleepy on a long drive, I prefer something more energizing.",
            },
        ],
        "script": [
            {
                "kind": "turn",
                "label": "Client call",
                "text": (
                    "I have a client call in ten minutes, and I want the cabin to stay quiet enough that I can hear every name and "
                    "number without asking people to repeat themselves."
                ),
            },
            {
                "kind": "turn",
                "label": "Long drive",
                "text": (
                    "After the call I still have a long highway stretch, so I also need the car to avoid making me drift off "
                    "during the rest of the drive."
                ),
            },
            {
                "kind": "summary",
                "label": "Offline summary",
                "text": "Summarize the work-call conversation into a reusable audio preference.",
            },
            {
                "kind": "turn",
                "label": "Audio choice",
                "text": "Now I am not sure whether to keep everything silent or switch to something more energizing.",
            },
            {
                "kind": "clarification",
                "label": "Clarification answer",
                "text": "Keep it silent until the call is over.",
            },
            {
                "kind": "turn",
                "label": "Reuse",
                "text": "I have the same call again tomorrow, and I need the cabin to stay quiet.",
            },
        ],
    },
    {
        "id": "rainy_evening_return",
        "title": "Rainy Evening Return",
        "subtitle": "Weather-aware comfort, sleeping child, and a second-day reuse test.",
        "demo_goal": (
            "Show a rainy evening return where the cabin stays quiet, the weather adds ambiguity, "
            "and the next similar drive reuses the learned choice."
        ),
        "memory_dimensions": [
            "weather_state",
            "family_trip",
            "music_mode",
            "temperature",
        ],
        "visual_focus": [
            "Weather Condition",
            "Quiet Cabin",
            "Reuse on Repeat Rain",
        ],
        "seed_preferences": [
            {
                "preference": "ac_temperature",
                "value": 22,
                "condition": {"type": "default"},
                "source": "user_stated",
                "evidence": "On normal evening drives, 22 C feels stable and easy to breathe in.",
            },
            {
                "preference": "ac_temperature",
                "value": 23.5,
                "condition": {
                    "type": "weather_state",
                    "operator": "==",
                    "target": "rainy",
                },
                "source": "user_stated",
                "evidence": "When it is rainy outside, a slightly warmer cabin feels better.",
            },
        ],
        "script": [
            {
                "kind": "turn",
                "label": "Rain starts",
                "text": (
                    "We are driving home through steady rain, and I want the cabin quiet because my daughter is asleep in the back seat."
                ),
            },
            {
                "kind": "turn",
                "label": "Evening drift",
                "text": (
                    "The road has been wet for a while, and I would rather keep the ride steady than make it swing too cold or too hot "
                    "while everyone is already tired."
                ),
            },
            {
                "kind": "summary",
                "label": "Offline summary",
                "text": "Summarize the rainy-evening conversation into a reusable comfort note.",
            },
            {
                "kind": "turn",
                "label": "Ambiguous cabin",
                "text": "It still feels wrong in here now, and I cannot tell whether the cabin should stay warmer because of the rain or cooler because I am getting impatient.",
            },
            {
                "kind": "clarification",
                "label": "Clarification answer",
                "text": "It is still raining hard outside, and the windows are fogging again.",
            },
            {
                "kind": "turn",
                "label": "Reuse",
                "text": "Next time we drive home after rain, it feels wrong in here again.",
            },
        ],
    },
]


_SCENARIO_INDEX = {scenario["id"]: scenario for scenario in SCENARIOS}


def list_demo_scenarios() -> list[dict[str, Any]]:
    return [copy.deepcopy(item) for item in SCENARIOS]


def get_demo_scenario(scenario_id: str) -> dict[str, Any]:
    normalized = _normalize_scenario_id(scenario_id)
    if normalized not in _SCENARIO_INDEX:
        raise KeyError(f"Unknown demo scenario: {scenario_id}")
    return copy.deepcopy(_SCENARIO_INDEX[normalized])


def seed_scenario_preferences(session: Any, scenario_id: str) -> list[Any]:
    scenario = get_demo_scenario(scenario_id)
    created: list[Any] = []
    for pref in scenario.get("seed_preferences", []):
        created.append(
            session.remember_preference(
                preference=pref["preference"],
                value=pref["value"],
                condition=pref["condition"],
                source=pref["source"],
                evidence=pref["evidence"],
            )
        )
    return created


def _normalize_scenario_id(scenario_id: str) -> str:
    text = str(scenario_id or "").strip()
    return SCENARIO_ALIASES.get(text, text)
