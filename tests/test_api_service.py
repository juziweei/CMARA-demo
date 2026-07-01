from __future__ import annotations

from http import HTTPStatus
import json
from pathlib import Path
from io import BytesIO

from src.action.car_functions import TOOLS_SCHEMA
from src.action.llm_client import ToolCall, ToolChatResponse
from src.interface.api_service import APIServiceError, DemoAPIService
from src.interface.http_api import create_handler
from src.interface.runtime import RuntimeBundle
from src.interface.session import DemoSession
from src.memory.clarification_learner import ClarificationLearner
from src.memory.lightmem_store import MemoryHit
from src.memory.offline_summarizer import OfflineSummarizer
from src.memory.preference_table import PreferenceTable
from src.policy.policy import Policy


class StubLLMClient:
    def chat(self, *, messages, tools, tool_choice="auto", temperature=0.0):
        prompt = messages[-1]["content"]
        if "好多了" in prompt:
            return ToolChatResponse(
                tool_calls=[
                    ToolCall(
                        name="set_ac_temperature",
                        arguments={"value": 25},
                    )
                ]
            )
        if "26.5" in prompt and "25" in prompt and "好热啊" in prompt:
            return ToolChatResponse(
                tool_calls=[
                    ToolCall(
                        name="ask_user",
                        arguments={
                            "question": "您感冒好些了吗？好了我设25度，还没好我设26.5度。"
                        },
                    )
                ]
            )
        raise AssertionError(f"Unexpected prompt:\n{prompt}")

    def complete(self, *, messages, temperature=0.0, response_format=None):
        system_prompt = messages[0]["content"]
        if "车载长期偏好抽取器" in system_prompt:
            return (
                '{"preferences":['
                '{"preference":"music_mode","value":"light",'
                '"condition":{"type":"default"},'
                '"evidence":"一家人出去玩，路上给我放轻音乐"}'
                "]}"
            )
        if "澄清学习" in system_prompt:
            return (
                '{"preference":"ac_temperature","value":25,'
                '"condition":{"type":"health_state","operator":"==","target":"recovering"},'
                '"evidence":"用户表示感冒基本恢复，希望设置25度。"}'
            )
        raise AssertionError(f"Unexpected complete call:\n{system_prompt}")

    def respond(self, *, messages, temperature=0.2):
        return "好的，我在。"


class StubMemoryStore:
    def __init__(self) -> None:
        self.add_calls: list[list[dict[str, str]]] = []

    def add(self, messages, *, force_segment: bool = False, force_extract: bool = False):
        self.add_calls.append(list(messages))
        return {"messages": list(messages)}

    def retrieve(self, query: str, limit: int = 5) -> list[str]:
        return []

    def retrieve_records(self, query: str, limit: int = 5) -> list[MemoryHit]:
        return []


def _build_runtime_bundle(preferences_path: Path) -> RuntimeBundle:
    table = PreferenceTable(preferences_path)
    llm_client = StubLLMClient()
    policy = Policy(llm_client=llm_client, tools_schema=TOOLS_SCHEMA)
    memory = StubMemoryStore()
    learner = ClarificationLearner(table, llm_client=llm_client)
    summarizer = OfflineSummarizer(llm_client=llm_client, preference_table=table)
    session = DemoSession(
        policy=policy,
        memory_store=memory,
        preference_table=table,
        learner=learner,
    )
    return RuntimeBundle(
        session=session,
        preference_table=table,
        summarizer=summarizer,
    )


def test_api_service_turn_and_clarification_round_trip(tmp_path: Path) -> None:
    preferences_path = tmp_path / "preferences.json"

    def runtime_factory() -> RuntimeBundle:
        return _build_runtime_bundle(preferences_path)

    def reset_callback() -> None:
        preferences_path.write_text("[]\n", encoding="utf-8")

    service = DemoAPIService(
        runtime_factory=runtime_factory,
        reset_callback=reset_callback,
    )
    runtime = service._state.runtime
    runtime.session.remember_preference(
        preference="ac_temperature",
        value=25,
        condition={"type": "default"},
        source="user_stated",
        evidence="用户说 25 度舒服",
    )
    runtime.session.remember_preference(
        preference="ac_temperature",
        value=26.5,
        condition={"type": "health_state", "operator": "==", "target": "sick"},
        source="user_stated",
        evidence="用户说感冒时调高一点",
    )

    first = service.turn(text="好热啊")

    assert first["status"] == "needs_user_input"
    assert first["pending"] is not None
    assert "感冒好些了吗" in first["assistant_text"]

    second = service.clarification(
        answer="好多了",
        pending_id=first["pending"]["pending_id"],
    )

    assert second["status"] == "acted"
    assert second["tool_result"]["tool"] == "set_ac_temperature"
    assert second["learned_preference"]["condition"] == {
        "type": "health_state",
        "operator": "==",
        "target": "recovering",
    }
    assert second["expired_preferences"][0]["condition"]["target"] == "sick"


def test_api_service_summarize_preferences_and_reset(tmp_path: Path) -> None:
    preferences_path = tmp_path / "preferences.json"

    def runtime_factory() -> RuntimeBundle:
        return _build_runtime_bundle(preferences_path)

    def reset_callback() -> None:
        preferences_path.write_text("[]\n", encoding="utf-8")

    service = DemoAPIService(
        runtime_factory=runtime_factory,
        reset_callback=reset_callback,
    )
    service._state.runtime.session.session_messages.extend(
        [
            {
                "role": "user",
                "content": "一家人出去玩，路上给我放轻音乐",
                "time_stamp": "2026-06-08T10:00:00",
            },
            {
                "role": "assistant",
                "content": "好的，已为您播放轻音乐",
                "time_stamp": "2026-06-08T10:00:01",
            },
        ]
    )

    summarized = service.summarize()

    assert summarized["count"] == 1
    prefs = service.preferences()
    assert prefs["count"] == 1
    assert prefs["preferences"][0]["preference"] == "music_mode"

    reset = service.reset()

    assert reset["status"] == "reset"
    assert service.preferences()["count"] == 0


def test_api_service_can_seed_family_trip_demo(tmp_path: Path) -> None:
    preferences_path = tmp_path / "preferences.json"

    def runtime_factory() -> RuntimeBundle:
        return _build_runtime_bundle(preferences_path)

    def reset_callback() -> None:
        preferences_path.write_text("[]\n", encoding="utf-8")

    service = DemoAPIService(
        runtime_factory=runtime_factory,
        reset_callback=reset_callback,
    )

    seeded = service.seed_family_trip_demo()

    assert seeded["status"] == "seeded"
    assert seeded["scenario"] == "family_trip"
    assert seeded["count"] == 2
    assert seeded["preferences"][0]["preference"] == "ac_temperature"
    assert seeded["preferences"][1]["condition"]["target"] == "sick"


def test_api_service_rejects_bad_requests(tmp_path: Path) -> None:
    preferences_path = tmp_path / "preferences.json"

    service = DemoAPIService(
        runtime_factory=lambda: _build_runtime_bundle(preferences_path),
        reset_callback=lambda: preferences_path.write_text("[]\n", encoding="utf-8"),
    )

    try:
        service.turn(text="")
    except APIServiceError as exc:
        assert "text must not be empty" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("expected APIServiceError")


def test_http_api_returns_json_error_for_invalid_body(tmp_path: Path) -> None:
    preferences_path = tmp_path / "preferences.json"
    service = DemoAPIService(
        runtime_factory=lambda: _build_runtime_bundle(preferences_path),
        reset_callback=lambda: preferences_path.write_text("[]\n", encoding="utf-8"),
    )
    handler_cls = create_handler(service)
    handler = handler_cls.__new__(handler_cls)
    handler.path = "/turn"
    handler.headers = {"Content-Length": str(len("{bad json"))}
    handler.rfile = BytesIO(b"{bad json")

    captured: list[tuple[HTTPStatus, str]] = []

    def _capture(status: HTTPStatus, message: str) -> None:
        captured.append((status, message))

    handler._send_error_payload = _capture  # type: ignore[method-assign]
    handler._dispatch = lambda fn: (_ for _ in ()).throw(AssertionError("unexpected dispatch"))  # type: ignore[method-assign]

    handler.do_POST()

    assert captured
    status, message = captured[0]
    assert status == HTTPStatus.BAD_REQUEST
    assert "invalid JSON body" in message

    try:
        service.clarification(answer="好多了", pending_id="missing")
    except APIServiceError as exc:
        assert exc.status_code == 404
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("expected APIServiceError")

    try:
        service.preferences(session_id="another")
    except APIServiceError as exc:
        assert "session_id='default'" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("expected APIServiceError")
