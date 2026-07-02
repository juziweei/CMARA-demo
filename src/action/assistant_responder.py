from __future__ import annotations

from typing import Mapping, Sequence

from src.action.llm_client import ToolChatClient


class AssistantResponder:
    SYSTEM_PROMPT = """
You are an in-car voice assistant.

Your job:
- Answer normal chat, explanations, suggestions, greetings, and companion-style conversation naturally.
- Keep responses concise, friendly, and suitable for a real voice assistant.
- Do not claim that you executed a vehicle-control action unless the tool layer actually did it.
- If the user is just chatting, do not force the message into a control command.
- If the user asks why the system acted or what it remembers, explain briefly.

Always respond in English.
Return plain text only. Do not return JSON or markdown.
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
        memory_block = "\n".join(memory_lines) if memory_lines else "- no relevant preferences"
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Recent conversation snippets:\n"
                    + "\n".join(f"{item['role']}: {item['content']}" for item in history)
                    + "\n\nCurrently relevant preferences:\n"
                    + memory_block
                    + "\n\nCurrent user input:\n"
                    + user_text
                ),
            },
        ]
        response = self.llm_client.respond(messages=messages, temperature=0.2).strip()
        return response or "Sure, I am here."
