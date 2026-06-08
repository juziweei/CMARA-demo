#!/usr/bin/env python3
"""Apply all frontend-related fixes to the CMARA server code."""
import os

BASE = '/root/vehicle_memory_demo'

# ── 1. car_functions.py ──
car_functions = r'''from __future__ import annotations

from typing import Any, Callable, Mapping

TOOLS_META: dict[str, dict[str, Any]] = {
    "set_ac_temperature": {"cost": "low", "reversible": True},
    "set_seat_heating": {"cost": "low", "reversible": True},
    "ask_user": {"cost": "zero", "reversible": True},
    "general_chat": {"cost": "zero", "reversible": True},
}

TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "set_ac_temperature",
            "description": "Set the cabin AC temperature in Celsius.",
            "parameters": {
                "type": "object",
                "properties": {
                    "value": {
                        "type": "number",
                        "description": "Target cabin temperature in Celsius.",
                    }
                },
                "required": ["value"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_seat_heating",
            "description": "Set the driver's seat heating level from 0 to 3.",
            "parameters": {
                "type": "object",
                "properties": {
                    "level": {
                        "type": "integer",
                        "description": "Seat heating level, where 0 is off and 3 is high.",
                    }
                },
                "required": ["level"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": "Ask the user a clarification question instead of guessing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "A concrete question that resolves the missing preference signal.",
                    }
                },
                "required": ["question"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "general_chat",
            "description": "Respond naturally to the user when their query is not a car-control request (greetings, small talk, questions about weather, news, etc.). Use this for any non-vehicle-function conversation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "response": {
                        "type": "string",
                        "description": "A natural, friendly response in Chinese to the user's non-car-control message.",
                    }
                },
                "required": ["response"],
                "additionalProperties": False,
            },
        },
    },
]


def set_ac_temperature(value: float) -> dict[str, Any]:
    temperature = float(value)
    return {
        "tool": "set_ac_temperature",
        "status": "executed",
        "value": temperature,
        "message": f"Set AC temperature to {temperature:g} C.",
    }


def set_seat_heating(level: int) -> dict[str, Any]:
    seat_level = int(level)
    if seat_level < 0 or seat_level > 3:
        raise ValueError("Seat heating level must be between 0 and 3.")
    return {
        "tool": "set_seat_heating",
        "status": "executed",
        "level": seat_level,
        "message": f"Set seat heating level to {seat_level}.",
    }


def ask_user(question: str) -> dict[str, Any]:
    text = str(question).strip()
    if not text:
        raise ValueError("Clarification question must not be empty.")
    return {
        "tool": "ask_user",
        "status": "needs_user_input",
        "question": text,
        "message": text,
    }


def general_chat(response: str) -> dict[str, Any]:
    text = str(response).strip()
    if not text:
        raise ValueError("General chat response must not be empty.")
    return {
        "tool": "general_chat",
        "status": "replied",
        "message": text,
    }


TOOL_EXECUTORS: dict[str, Callable[..., dict[str, Any]]] = {
    "set_ac_temperature": set_ac_temperature,
    "set_seat_heating": set_seat_heating,
    "ask_user": ask_user,
    "general_chat": general_chat,
}


def run_tool(name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
    if name not in TOOL_EXECUTORS:
        raise KeyError(f"Unknown tool: {name}")
    return TOOL_EXECUTORS[name](**dict(arguments))
'''

# ── 2. policy.py (system prompt update) ──
policy_py_path = os.path.join(BASE, 'src/policy/policy.py')
with open(policy_py_path, 'r') as f:
    policy_content = f.read()

old_prompt_start = '你是一个车载智能助手的动作决策器。你的职责只有一个：在当前轮从可用工具中选择 1 个。'
new_prompt_start = '''你是一个车载智能助手的动作决策器。你的职责只有一个：在当前轮从可用工具中选择 1 个。

你可以做三类决策：
1. ACT：直接调用车控工具执行动作（set_ac_temperature / set_seat_heating）
2. ASK：调用 ask_user(question) 追问 1 个最小必要信息
3. CHAT：调用 general_chat(response) 回复与车辆控制无关的日常对话

你会收到：
- 用户当前说的话
- 系统从长期记忆中检索到的 active 偏好

请按下面顺序在内部判断，然后只输出 tool call：

步骤0：先判断用户的意图是不是"车辆控制相关"
- 如果你确定用户不是在请求车辆控制（例如只是打招呼、闲聊、问天气、问新闻等），直接调用 general_chat 给出自然友好的回复。
- 不要生硬地拒绝用户或把话题强行转到车上——友好自然地回复即可。
- 如果用户的话可以同时理解成闲聊和车控请求，优先按车控处理。

步骤1：提取"当前话语里已经明确给出的事实"
- 只有用户明确说出的事实才算成立。
- 不要脑补、不要根据常识补全、不要假设用户的状态。

步骤2：找出"与当前动作相关"的候选偏好
- 只看和当前请求同一偏好对象、同一动作相关的偏好。
- 无关偏好忽略，不要因为记忆里有别的偏好就追问无关问题。

步骤3：判断是否已经能唯一确定动作
- 如果用户当前话语本身已经明确给出了动作或参数，直接执行，不需要再问。
- 如果只有一条相关偏好，且它的触发条件在当前情境下明确成立，直接执行。
- 如果一条偏好带有更具体的条件，而该条件在当前情境下被明确满足，另一条只是 default 兜底偏好，则优先执行更具体的那条，不要再问。
- 如果有多条候选偏好，但它们最终指向同一个工具和同一参数，也直接执行，不要因为"条数多"而提问。
- 当条件已经明确、动作代价低且可逆时，直接执行，不要多问。

步骤4：只有在"缺少一个决定动作所必需的关键信息"时，才 ask_user
- 如果多条偏好互相冲突，或者都可能适用，但当前情境无法区分，不要猜，调用 ask_user。
- 如果偏好的触发条件依赖某个缺失信息，例如健康状态、天气、是否疲劳，而用户当前并没有提供这个信息，不要假设，调用 ask_user。
- 如果当前话语已经是对上一轮澄清问题的直接回答，并且这个回答已经补全了缺失信息，就不得重复追问同一个维度，必须直接执行。
- 如果当前没有任何相关偏好，且用户当前话语也没有明确给出可执行参数，但用户意图明显是车控相关的，调用 ask_user 收集最小必要偏好。'''

if old_prompt_start in policy_content:
    # Find the old prompt boundaries
    old_prompt_end = '硬约束：\n- 只能基于用户当前话语和检索到的偏好判断，不要编造偏好里没有的信息。\n- 不要为了显得谨慎而过度追问；只有在缺少关键区分信息时才问。\n- 只通过 tool call 作答，不要输出普通文本答案。'
    new_prompt_end = '''硬约束：
- 只能基于用户当前话语和检索到的偏好判断，不要编造偏好里没有的信息。
- 不要为了显得谨慎而过度追问；只有在缺少关键区分信息时才问。
- 只通过 tool call 作答，不要输出普通文本答案。
- 非车控对话用 general_chat，车控对话用 set_ac_temperature / set_seat_heating / ask_user。'''
    policy_content = policy_content.replace(old_prompt_end, new_prompt_end)
    policy_content = policy_content.replace(old_prompt_start, new_prompt_start)
    with open(policy_py_path, 'w') as f:
        f.write(policy_content)
    print('[OK] policy.py updated')
else:
    print('[SKIP] policy.py - prompt already updated or not found')

# ── 3. session.py (general_chat status) ──
session_py_path = os.path.join(BASE, 'src/interface/session.py')
with open(session_py_path, 'r') as f:
    session_content = f.read()

old_session = '''        assistant_message = {
            "role": "assistant",
            "content": tool_result["message"],
            "time_stamp": _now(),
        }
        self.session_messages.append(assistant_message)
        self.memory_store.add([*memory_inputs, assistant_message])
        return TurnResult(
            status="acted",
            assistant_text=tool_result["message"],'''

new_session = '''        # general_chat and car-function ACT both go here
        status = "replied" if decision.tool_name == "general_chat" else "acted"
        assistant_message = {
            "role": "assistant",
            "content": tool_result["message"],
            "time_stamp": _now(),
        }
        self.session_messages.append(assistant_message)
        self.memory_store.add([*memory_inputs, assistant_message])
        return TurnResult(
            status=status,
            assistant_text=tool_result["message"],'''

if old_session in session_content:
    session_content = session_content.replace(old_session, new_session)
    with open(session_py_path, 'w') as f:
        f.write(session_content)
    print('[OK] session.py updated')
else:
    print('[SKIP] session.py - already updated or pattern not found')

# ── Write car_functions.py ──
cf_path = os.path.join(BASE, 'src/action/car_functions.py')
with open(cf_path, 'w') as f:
    f.write(car_functions)
print('[OK] car_functions.py written')
print('\nAll updates applied. Restart the API server to take effect.')
