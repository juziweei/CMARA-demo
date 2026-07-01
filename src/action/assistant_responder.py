from __future__ import annotations

from typing import Mapping, Sequence

from src.action.llm_client import ToolChatClient


class AssistantResponder:
    SYSTEM_PROMPT = """
你是一个车载语音助手。

你的任务：
- 对普通聊天、解释、闲聊、建议、问候、陪伴式对话做自然回答；
- 回答要简洁、友好、像真实语音助手；
- 不要编造自己已经执行了车控动作；
- 如果用户只是聊天，不要硬转成控制命令；
- 如果用户在问系统现在为什么这么做、记住了什么，也可以直接解释。

输出纯文本，不要输出 JSON，不要输出 markdown。
""".strip()

    def __init__(self, *, llm_client: ToolChatClient) -> None:
        self.llm_client = llm_client

    def respond(
        self,
        *,
        user_text: str,
        retrieved_prefs: Sequence[Mapping[str, object]],
        session_messages: Sequence[Mapping[str, str]],
    ) -> str:
        history = list(session_messages[-6:])
        memory_lines: list[str] = []
        for pref in retrieved_prefs[:5]:
            memory_lines.append(
                f"- {pref.get('preference')}={pref.get('value')} | "
                f"{pref.get('condition_text') or pref.get('condition')} | "
                f"{pref.get('source', 'unknown')}"
            )
        memory_block = "\n".join(memory_lines) if memory_lines else "- （无相关偏好）"
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "最近对话片段：\n"
                    + "\n".join(f"{item['role']}: {item['content']}" for item in history)
                    + "\n\n当前相关偏好：\n"
                    + memory_block
                    + "\n\n当前用户输入：\n"
                    + user_text
                ),
            },
        ]
        response = self.llm_client.respond(messages=messages, temperature=0.2).strip()
        return response or "好的，我在。"
