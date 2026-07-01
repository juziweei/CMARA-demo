from __future__ import annotations

from pathlib import Path

from src.action.car_functions import TOOLS_SCHEMA
from src.action.assistant_responder import AssistantResponder
from src.action.llm_client import ToolCall, ToolChatResponse
from src.interface.session import DemoSession
from src.memory.clarification_learner import ClarificationLearner
from src.memory.lightmem_store import MemoryHit
from src.memory.offline_summarizer import OfflineSummarizer
from src.memory.preference_table import Condition, PreferenceTable
from src.policy.policy import Policy, build_user_prompt, prepare_policy_inputs


class StubLLMClient:
    def chat(self, *, messages, tools, tool_choice="auto", temperature=0.0):
        prompt = messages[-1]["content"]
        if "当前明确指令：set_ac_temperature(value=24)" in prompt:
            return ToolChatResponse(
                tool_calls=[
                    ToolCall(
                        name="set_ac_temperature",
                        arguments={"value": 24},
                    )
                ]
            )
        if "感冒恢复了" in prompt and "health_state == recovering" in prompt:
            return ToolChatResponse(
                tool_calls=[
                    ToolCall(
                        name="set_ac_temperature",
                        arguments={"value": 25},
                    )
                ]
            )
        if "好多了" in prompt:
            return ToolChatResponse(
                tool_calls=[
                    ToolCall(
                        name="set_ac_temperature",
                        arguments={"value": 25},
                    )
                ]
            )
        if "轻音乐" in prompt and "提神音乐" in prompt and "出发吧" in prompt:
            return ToolChatResponse(
                tool_calls=[
                    ToolCall(
                        name="ask_user",
                        arguments={
                            "question": "您现在想听轻音乐，还是需要更提神一点的音乐？"
                        },
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
        if "默认（无特殊条件）" in prompt and "好热啊" in prompt:
            return ToolChatResponse(
                tool_calls=[
                    ToolCall(
                        name="set_ac_temperature",
                        arguments={"value": 25},
                    )
                ]
            )
        raise AssertionError(f"Unexpected prompt:\n{prompt}")

    def complete(self, *, messages, temperature=0.0, response_format=None):
        system_prompt = messages[0]["content"]
        prompt = messages[-1]["content"]
        if "车载长期偏好抽取器" in system_prompt:
            return (
                '{"preferences":['
                '{"preference":"music_mode","value":"light",'
                '"condition":{"type":"default"},'
                '"evidence":"一家人长途出游时，用户习惯放轻音乐"}'
                "]}"
            )
        if "tool_name" in prompt and "question" in prompt and "answer" in prompt:
            return (
                '{"preference":"ac_temperature","value":25,'
                '"condition":{"type":"health_state","operator":"==","target":"recovering"},'
                '"evidence":"5.5 天热且感冒恢复时，询问后用户选 25 度"}'
            )
        raise NotImplementedError

    def respond(self, *, messages, temperature=0.2):
        prompt = messages[-1]["content"]
        if "今天天气怎么样" in prompt:
            return "今天天气我暂时查不到实时数据，不过如果你愿意，我可以先根据车内需求帮你调节空调或座椅。"
        if "有点无聊" in prompt:
            return "要不要我陪你聊聊天，或者帮你想个更轻松的出行氛围？"
        return "好的，我在。"


class StubMemoryStore:
    def __init__(self, hits_by_query: dict[str, list[str]] | None = None) -> None:
        self.hits_by_query = hits_by_query or {}
        self.added_messages: list[dict[str, str]] = []
        self.add_calls: list[list[dict[str, str]]] = []

    def add(self, messages, *, force_segment: bool = False, force_extract: bool = False):
        self.add_calls.append(list(messages))
        self.added_messages.extend(messages)
        return {"messages": list(messages)}

    def retrieve(self, query: str, limit: int = 5) -> list[str]:
        return self.hits_by_query.get(query, [])[:limit]

    def retrieve_records(self, query: str, limit: int = 5) -> list[MemoryHit]:
        return [
            MemoryHit(id=f"hit-{index}", memory=text)
            for index, text in enumerate(self.retrieve(query, limit=limit), start=1)
        ]

    def offline_extract(self, messages):
        return self.add(messages, force_segment=True, force_extract=True)


class UnsupportedSummaryLLMClient(StubLLMClient):
    def complete(self, *, messages, temperature=0.0, response_format=None):
        system_prompt = messages[0]["content"]
        if "车载长期偏好抽取器" in system_prompt:
            return (
                '{"preferences":['
                '{"preference":"车内安静","value":true,'
                '"condition":{"type":"default"},'
                '"evidence":"家庭出游时希望车里安静"},'
                '{"preference":"music_mode","value":"light",'
                '"evidence":""}'
                "]}"
            )
        return super().complete(
            messages=messages,
            temperature=temperature,
            response_format=response_format,
        )


class MissingConditionSummaryLLMClient(StubLLMClient):
    def complete(self, *, messages, temperature=0.0, response_format=None):
        system_prompt = messages[0]["content"]
        if "车载长期偏好抽取器" in system_prompt:
            return (
                '{"preferences":['
                '{"preference":"空调","value":24,'
                '"evidence":"用户说一家人出游时 24 度最舒服"}'
                "]}"
            )
        return super().complete(
            messages=messages,
            temperature=temperature,
            response_format=response_format,
        )


class FreeTextClarificationLLMClient(StubLLMClient):
    def complete(self, *, messages, temperature=0.0, response_format=None):
        prompt = messages[-1]["content"]
        if "tool_name" in prompt and "question" in prompt and "answer" in prompt:
            return (
                '{"preference":"空调温度设置为25度","value":"25度",'
                '"condition":{"type":"health_state","operator":"==","target":"healthy"},'
                '"evidence":"用户表示感冒已经基本恢复，选择了将空调温度设置为25度。"}'
            )
        return super().complete(
            messages=messages,
            temperature=temperature,
            response_format=response_format,
        )


class RetryClarificationLLMClient(StubLLMClient):
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, *, messages, temperature=0.0, response_format=None):
        self.calls += 1
        system_prompt = messages[0]["content"]
        if "JSON 修复器" in system_prompt:
            return (
                '{"preference":"ac_temperature","value":25,'
                '"condition":{"type":"health_state","operator":"==","target":"recovering"},'
                '"evidence":"用户说好多了，选择了25度。"}'
            )
        if "tool_name" in messages[-1]["content"]:
            return "```json\nnot valid\n```"
        return super().complete(
            messages=messages,
            temperature=temperature,
            response_format=response_format,
        )


class PassengerHealthClarificationLLMClient(StubLLMClient):
    def complete(self, *, messages, temperature=0.0, response_format=None):
        prompt = messages[-1]["content"]
        if "tool_name" in prompt and "question" in prompt and "answer" in prompt:
            return (
                '{"preference":"ac_temperature","value":26,'
                '"condition":{"type":"passenger_health_state","operator":"==","target":"sick"},'
                '"evidence":"用户说明妻子今天不舒服，因此选择把空调调高到26度。"}'
            )
        return super().complete(
            messages=messages,
            temperature=temperature,
            response_format=response_format,
        )


def test_policy_asks_when_preferences_conflict() -> None:
    policy = Policy(llm_client=StubLLMClient(), tools_schema=TOOLS_SCHEMA)
    decision = policy.decide(
        context="好热啊",
        retrieved_prefs=[
            {
                "id": 1,
                "preference": "ac_temperature",
                "value": 25,
                "condition": {"type": "default"},
                "condition_text": "默认（无特殊条件）",
                "source": "user_stated",
                "evidence": "用户说 25 度舒服",
            },
            {
                "id": 2,
                "preference": "ac_temperature",
                "value": 26.5,
                "condition": {
                    "type": "health_state",
                    "operator": "==",
                    "target": "sick",
                },
                "condition_text": "health_state == sick",
                "source": "user_stated",
                "evidence": "用户说感冒时调高一点",
            },
        ],
    )
    assert decision.action == "ASK"
    assert decision.tool_name == "ask_user"
    assert "感冒好些了吗" in decision.question


def test_policy_acts_when_single_preference_is_clear() -> None:
    policy = Policy(llm_client=StubLLMClient(), tools_schema=TOOLS_SCHEMA)
    decision = policy.decide(
        context="好热啊",
        retrieved_prefs=[
            {
                "id": 1,
                "preference": "ac_temperature",
                "value": 25,
                "condition": {"type": "default"},
                "condition_text": "默认（无特殊条件）",
                "source": "user_stated",
                "evidence": "用户说 25 度舒服",
            }
        ],
    )
    assert decision.action == "ACT"
    assert decision.tool_name == "set_ac_temperature"
    assert decision.tool_args == {"value": 25}


def test_policy_generalizes_to_music_scenario() -> None:
    policy = Policy(llm_client=StubLLMClient(), tools_schema=TOOLS_SCHEMA)
    decision = policy.decide(
        context="出发吧",
        retrieved_prefs=[
            {
                "id": 1,
                "preference": "music_mode",
                "value": "light",
                "condition": {"type": "default"},
                "condition_text": "默认（无特殊条件）",
                "source": "offline_summary",
                "evidence": "用户平时偏好轻音乐",
            },
            {
                "id": 2,
                "preference": "music_mode",
                "value": "energizing",
                "condition": {
                    "type": "fatigue_state",
                    "operator": "==",
                    "target": "sleepy",
                },
                "condition_text": "fatigue_state == sleepy",
                "source": "user_stated",
                "evidence": "犯困时想听提神音乐",
            },
        ],
    )
    assert decision.action == "ASK"
    assert "轻音乐" in decision.question
    assert "提神" in decision.question


def test_policy_prefers_explicit_user_parameter_over_history() -> None:
    policy = Policy(llm_client=StubLLMClient(), tools_schema=TOOLS_SCHEMA)
    decision = policy.decide(
        context="把空调调到24度",
        retrieved_prefs=[
            {
                "id": 1,
                "preference": "ac_temperature",
                "value": 25,
                "condition": {"type": "default"},
                "condition_text": "默认（无特殊条件）",
                "source": "user_stated",
                "evidence": "用户说 25 度舒服",
            }
        ],
    )
    assert decision.action == "ACT"
    assert decision.tool_name == "set_ac_temperature"
    assert decision.tool_args == {"value": 24}


def test_policy_acts_after_clarification_answer() -> None:
    policy = Policy(llm_client=StubLLMClient(), tools_schema=TOOLS_SCHEMA)
    decision = policy.decide(
        context="用户先说：好热啊\n系统追问：您感冒好些了吗？好了我设25度，还没好我设26.5度。\n用户回答：好多了",
        retrieved_prefs=[
            {
                "id": 1,
                "preference": "ac_temperature",
                "value": 25,
                "condition": {"type": "default"},
                "condition_text": "默认（无特殊条件）",
                "source": "user_stated",
                "evidence": "用户说 25 度舒服",
            },
            {
                "id": 2,
                "preference": "ac_temperature",
                "value": 26.5,
                "condition": {
                    "type": "health_state",
                    "operator": "==",
                    "target": "sick",
                },
                "condition_text": "health_state == sick",
                "source": "user_stated",
                "evidence": "用户说感冒时调高一点",
            },
        ],
    )
    assert decision.action == "ACT"
    assert decision.tool_name == "set_ac_temperature"
    assert decision.tool_args == {"value": 25}


def test_policy_prefers_specific_recovery_preference_over_default() -> None:
    policy = Policy(llm_client=StubLLMClient(), tools_schema=TOOLS_SCHEMA)
    decision = policy.decide(
        context="感冒恢复了，还是有点热",
        retrieved_prefs=[
            {
                "id": 1,
                "preference": "ac_temperature",
                "value": 25,
                "condition": {"type": "default"},
                "condition_text": "默认（无特殊条件）",
                "source": "user_stated",
                "evidence": "用户说 25 度舒服",
            },
            {
                "id": 3,
                "preference": "ac_temperature",
                "value": 25,
                "condition": {
                    "type": "health_state",
                    "operator": "==",
                    "target": "recovering",
                },
                "condition_text": "health_state == recovering",
                "source": "learned_from_clarification",
                "evidence": "感冒恢复后会选 25 度",
            },
        ],
    )
    assert decision.action == "ACT"
    assert decision.tool_name == "set_ac_temperature"
    assert decision.tool_args == {"value": 25}


def test_preference_lifecycle_and_clarification_learning(tmp_path: Path) -> None:
    table = PreferenceTable(tmp_path / "preferences.json")
    default_pref = table.add_preference(
        preference="ac_temperature",
        value=25,
        condition=Condition(type="default"),
        source="user_stated",
        evidence="用户说 25 度舒服",
    )
    sick_pref = table.add_preference(
        preference="ac_temperature",
        value=26.5,
        condition=Condition(type="health_state", operator="==", target="sick"),
        source="user_stated",
        evidence="用户说感冒时调高一点",
    )

    expired = table.mark_matching_expired(
        preference="ac_temperature",
        condition_type="health_state",
        condition_target="sick",
    )
    assert [record.id for record in expired] == [sick_pref.id]

    learner = ClarificationLearner(table)
    learned = learner.learn(
        preference="ac_temperature",
        chosen_value=default_pref.value,
        question_dimension="health_state",
        dimension_value="recovering",
        evidence="5.5 天热且感冒恢复时，询问后用户选 25 度",
    )
    assert learned.source == "learned_from_clarification"
    assert learned.condition.target == "recovering"
    assert len(table.get_active("ac_temperature")) == 2


def test_clarification_learning_is_idempotent(tmp_path: Path) -> None:
    table = PreferenceTable(tmp_path / "preferences.json")
    learner = ClarificationLearner(table)

    first = learner.learn(
        preference="ac_temperature",
        chosen_value=25,
        question_dimension="health_state",
        dimension_value="recovering",
        evidence="恢复后选 25 度",
    )
    second = learner.learn(
        preference="ac_temperature",
        chosen_value=25,
        question_dimension="health_state",
        dimension_value="recovering",
        evidence="恢复后选 25 度",
    )

    assert first.id == second.id
    assert len(table.get_active("ac_temperature")) == 1


def test_dialogue_learning_uses_llm_extracted_condition(tmp_path: Path) -> None:
    table = PreferenceTable(tmp_path / "preferences.json")
    learner = ClarificationLearner(table, llm_client=StubLLMClient())
    learned = learner.learn_from_dialogue(
        context="好热啊",
        question="您感冒好些了吗？好了我设25度，还没好我设26.5度。",
        answer="好多了",
        tool_name="set_ac_temperature",
        tool_args={"value": 25},
        retrieved_prefs=[
            {
                "id": 1,
                "preference": "ac_temperature",
                "value": 25,
                "condition": {"type": "default"},
                "condition_text": "默认（无特殊条件）",
                "source": "user_stated",
                "evidence": "用户说 25 度舒服",
            },
            {
                "id": 2,
                "preference": "ac_temperature",
                "value": 26.5,
                "condition": {
                    "type": "health_state",
                    "operator": "==",
                    "target": "sick",
                },
                "condition_text": "health_state == sick",
                "source": "user_stated",
                "evidence": "用户说感冒时调高一点",
            },
        ],
    )
    assert learned.preference == "ac_temperature"
    assert learned.value == 25
    assert learned.condition.type == "health_state"
    assert learned.condition.target == "recovering"


def test_dialogue_learning_normalizes_free_text_preference_and_health_answer(
    tmp_path: Path,
) -> None:
    table = PreferenceTable(tmp_path / "preferences.json")
    learner = ClarificationLearner(table, llm_client=FreeTextClarificationLLMClient())
    learned = learner.learn_from_dialogue(
        context="好热啊",
        question="您感冒好些了吗？好了我设25度，还没好我设26.5度。",
        answer="好多了，今天基本恢复了。",
        tool_name="set_ac_temperature",
        tool_args={"value": 25},
        retrieved_prefs=[
            {
                "id": 1,
                "preference": "ac_temperature",
                "value": 26.5,
                "condition": {
                    "type": "health_state",
                    "operator": "==",
                    "target": "sick",
                },
                "condition_text": "health_state == sick",
                "source": "user_stated",
                "evidence": "用户说感冒时调高一点",
            }
        ],
    )

    assert learned.preference == "ac_temperature"
    assert learned.value == 25
    assert learned.condition.type == "health_state"
    assert learned.condition.target == "recovering"


def test_dialogue_learning_retries_invalid_json_response(tmp_path: Path) -> None:
    table = PreferenceTable(tmp_path / "preferences.json")
    llm_client = RetryClarificationLLMClient()
    learner = ClarificationLearner(table, llm_client=llm_client)
    learned = learner.learn_from_dialogue(
        context="好热啊",
        question="您感冒好些了吗？好了我设25度，还没好我设26.5度。",
        answer="好多了",
        tool_name="set_ac_temperature",
        tool_args={"value": 25},
        retrieved_prefs=[],
    )

    assert llm_client.calls == 2
    assert learned.preference == "ac_temperature"
    assert learned.condition.target == "recovering"


def test_reconcile_recovery_expires_sick_preference(tmp_path: Path) -> None:
    table = PreferenceTable(tmp_path / "preferences.json")
    sick = table.add_preference(
        preference="ac_temperature",
        value=26.5,
        condition=Condition(type="health_state", operator="==", target="sick"),
        source="user_stated",
        evidence="感冒时调高一点",
    )
    learner = ClarificationLearner(table)
    learned = learner.learn(
        preference="ac_temperature",
        chosen_value=25,
        question_dimension="health_state",
        dimension_value="recovering",
        evidence="恢复后选 25 度",
    )
    expired = learner.reconcile_learned_preference(learned)
    assert [record.id for record in expired] == [sick.id]


def test_learn_normalizes_chinese_health_state(tmp_path: Path) -> None:
    table = PreferenceTable(tmp_path / "preferences.json")
    learner = ClarificationLearner(table)
    learned = learner.learn(
        preference="ac_temperature",
        chosen_value=25,
        question_dimension="health_state",
        dimension_value="好多了",
        evidence="用户说好多了",
    )
    assert learned.condition.target == "recovering"


def test_demo_session_closes_ask_act_learn_expire_flow(tmp_path: Path) -> None:
    table = PreferenceTable(tmp_path / "preferences.json")
    table.add_preference(
        preference="ac_temperature",
        value=25,
        condition=Condition(type="default"),
        source="user_stated",
        evidence="默认 25 度",
    )
    table.add_preference(
        preference="ac_temperature",
        value=26.5,
        condition=Condition(type="health_state", operator="==", target="sick"),
        source="user_stated",
        evidence="感冒时 26.5 度",
    )
    memory = StubMemoryStore(
        hits_by_query={
            "好热啊": ["默认 25 度", "感冒时 26.5 度"],
            "用户先说：好热啊\n系统追问：您感冒好些了吗？好了我设25度，还没好我设26.5度。\n用户回答：好多了": [
                "默认 25 度",
                "感冒时 26.5 度",
            ],
        }
    )
    learner = ClarificationLearner(table, llm_client=StubLLMClient())
    policy = Policy(llm_client=StubLLMClient(), tools_schema=TOOLS_SCHEMA)
    session = DemoSession(
        policy=policy,
        memory_store=memory,
        preference_table=table,
        learner=learner,
        responder=AssistantResponder(llm_client=StubLLMClient()),
    )

    initial = session.handle_user_message("好热啊")
    assert initial.status == "needs_user_input"
    assert initial.pending is not None
    follow_up = session.handle_clarification(initial.pending, "好多了")

    assert follow_up.status == "acted"
    assert follow_up.tool_result is not None
    assert follow_up.tool_result["tool"] == "set_ac_temperature"
    assert follow_up.learned_preference is not None
    assert follow_up.learned_preference.condition.target == "recovering"
    assert [record.condition.target for record in follow_up.expired_preferences] == ["sick"]
    active_targets = {
        record.condition.target
        for record in table.get_active("ac_temperature")
        if record.condition.type == "health_state"
    }
    assert active_targets == {"recovering"}
    assert len(memory.add_calls) == 2
    assert [message["role"] for message in memory.add_calls[0]] == ["user", "assistant"]
    assert memory.add_calls[0][0]["content"] == "好热啊"
    assert "感冒好些了吗" in memory.add_calls[0][1]["content"]
    assert [message["role"] for message in memory.add_calls[1]] == ["user", "assistant"]
    assert memory.add_calls[1][0]["content"] == "好多了"
    assert "25" in memory.add_calls[1][1]["content"]
    assert follow_up.decision_trace["decision"]["tool_name"] == "set_ac_temperature"
    assert "policy_candidates" in follow_up.decision_trace
    assert "retrieval_hits" in follow_up.decision_trace


def test_demo_session_uses_llm_for_general_chat(tmp_path: Path) -> None:
    table = PreferenceTable(tmp_path / "preferences.json")
    memory = StubMemoryStore()
    learner = ClarificationLearner(table, llm_client=StubLLMClient())
    policy = Policy(llm_client=StubLLMClient(), tools_schema=TOOLS_SCHEMA)
    session = DemoSession(
        policy=policy,
        memory_store=memory,
        preference_table=table,
        learner=learner,
        responder=AssistantResponder(llm_client=StubLLMClient()),
    )

    result = session.handle_user_message("今天天气怎么样？")

    assert result.status == "replied"
    assert result.tool_result is not None
    assert result.tool_result["tool"] == "general_chat"
    assert "天气" in result.assistant_text
    assert memory.add_calls[-1][1]["content"] == result.assistant_text


def test_clarification_learning_can_use_passenger_health_state(tmp_path: Path) -> None:
    table = PreferenceTable(tmp_path / "preferences.json")
    learner = ClarificationLearner(
        table,
        llm_client=PassengerHealthClarificationLLMClient(),
    )

    learned = learner.learn_from_dialogue(
        context="我妻子今天不舒服，车里有点冷。",
        question="您是想把空调调高一些照顾她吗？",
        answer="对，调到26度吧。",
        tool_name="set_ac_temperature",
        tool_args={"value": 26},
        retrieved_prefs=[],
    )

    assert learned.preference == "ac_temperature"
    assert learned.value == 26
    assert learned.condition.type == "passenger_health_state"
    assert learned.condition.target == "sick"


def test_offline_summarizer_is_idempotent(tmp_path: Path) -> None:
    table = PreferenceTable(tmp_path / "preferences.json")
    memory = StubMemoryStore()
    summarizer = OfflineSummarizer(
        llm_client=StubLLMClient(),
        preference_table=table,
    )
    messages = [
        {"role": "user", "content": "一家人出去玩，路上给我放轻音乐", "time_stamp": "2026-06-03T10:00:00"},
        {"role": "assistant", "content": "好的，已为您播放轻音乐", "time_stamp": "2026-06-03T10:00:05"},
    ]

    first = summarizer.summarize(messages)
    second = summarizer.summarize(messages)

    assert len(first) == 1
    assert second == []
    active = table.get_active("music_mode")
    assert len(active) == 1
    assert active[0].value == "light"


def test_offline_summarizer_skips_unsupported_or_evidence_less_preferences(tmp_path: Path) -> None:
    table = PreferenceTable(tmp_path / "preferences.json")
    memory = StubMemoryStore()
    summarizer = OfflineSummarizer(
        llm_client=UnsupportedSummaryLLMClient(),
        preference_table=table,
    )
    messages = [
        {"role": "user", "content": "一家人出去玩的时候，车里安静一点。", "time_stamp": "2026-06-03T10:00:00"},
    ]

    added = summarizer.summarize(messages)

    assert added == []
    assert table.list_preferences() == []


def test_offline_summarizer_defaults_missing_condition(tmp_path: Path) -> None:
    table = PreferenceTable(tmp_path / "preferences.json")
    memory = StubMemoryStore()
    summarizer = OfflineSummarizer(
        llm_client=MissingConditionSummaryLLMClient(),
        preference_table=table,
    )
    messages = [
        {"role": "user", "content": "一家人出游时 24 度舒服。", "time_stamp": "2026-06-03T10:00:00"},
    ]

    added = summarizer.summarize(messages)

    assert len(added) == 1
    assert added[0].preference == "ac_temperature"
    assert added[0].condition.type == "default"


def test_prepare_policy_inputs_merges_same_action_candidates() -> None:
    prepared = prepare_policy_inputs(
        context="感冒恢复了，还是有点热",
        retrieved_prefs=[
            {
                "id": 1,
                "preference": "ac_temperature",
                "value": 25,
                "condition": {"type": "default"},
                "condition_text": "默认（无特殊条件）",
                "source": "user_stated",
                "evidence": "用户说 25 度舒服",
            },
            {
                "id": 2,
                "preference": "ac_temperature",
                "value": 25,
                "condition": {
                    "type": "health_state",
                    "operator": "==",
                    "target": "recovering",
                },
                "condition_text": "health_state == recovering",
                "source": "learned_from_clarification",
                "evidence": "恢复后会选 25 度",
            },
        ],
    )

    assert len(prepared.retrieved_prefs) == 1
    assert prepared.retrieved_prefs[0]["condition"]["type"] == "merged"
    assert prepared.trace["unknown_dimensions"] == []


def test_prepare_policy_inputs_filters_irrelevant_preferences() -> None:
    prepared = prepare_policy_inputs(
        context="周末一家人要去海边了，好热啊。",
        retrieved_prefs=[
            {
                "id": 1,
                "preference": "ac_temperature",
                "value": 24,
                "condition": {"type": "default"},
                "condition_text": "默认（无特殊条件）",
                "source": "user_stated",
                "evidence": "一家人出游时 24 度舒服",
                "matched_by": "query:热",
                "retrieval_score": 120,
                "query_score": 10,
            },
            {
                "id": 2,
                "preference": "music_mode",
                "value": "silent",
                "condition": {"type": "default"},
                "condition_text": "默认（无特殊条件）",
                "source": "offline_summary",
                "evidence": "一家人出游时车里安静一点",
                "matched_by": "hit:一家人出游时车里安静一点",
                "retrieval_score": 25,
                "query_score": 0,
            },
        ],
    )

    assert [item["preference"] for item in prepared.retrieved_prefs] == ["ac_temperature"]
    assert [item["preference"] for item in prepared.trace["filtered_out_preferences"]] == [
        "music_mode"
    ]


def test_user_prompt_contains_structured_sections_and_match_reason() -> None:
    prompt = build_user_prompt(
        "好热啊",
        [
            {
                "id": 9,
                "preference": "ac_temperature",
                "value": 25,
                "condition": {"type": "default"},
                "condition_text": "默认（无特殊条件）",
                "source": "user_stated",
                "evidence": "用户说 25 度舒服",
                "matched_by": "query:热",
            }
        ],
    )
    assert "当前用户请求：" in prompt
    assert "从当前话语可直接确认的事实：" in prompt
    assert "候选偏好：" in prompt
    assert "仍未知的关键维度：" in prompt
    assert "决策要求：" in prompt
    assert "preference: ac_temperature" in prompt
    assert "condition.type: default" in prompt
    assert "matched_by: query:热" in prompt
