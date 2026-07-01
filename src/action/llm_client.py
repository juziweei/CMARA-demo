from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence

from openai import OpenAI


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolChatResponse:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


class ToolChatClient(Protocol):
    def chat(
        self,
        *,
        messages: Sequence[Mapping[str, str]],
        tools: Sequence[Mapping[str, Any]],
        tool_choice: str = "auto",
        temperature: float = 0.0,
    ) -> ToolChatResponse:
        ...

    def complete(
        self,
        *,
        messages: Sequence[Mapping[str, str]],
        temperature: float = 0.0,
        response_format: Mapping[str, str] | None = None,
    ) -> str:
        ...

    def respond(
        self,
        *,
        messages: Sequence[Mapping[str, str]],
        temperature: float = 0.2,
    ) -> str:
        ...


class OpenAIToolClient:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str = "EMPTY",
        timeout: float = 60.0,
    ) -> None:
        self.model = model
        self._client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)

    def chat(
        self,
        *,
        messages: Sequence[Mapping[str, str]],
        tools: Sequence[Mapping[str, Any]],
        tool_choice: str = "auto",
        temperature: float = 0.0,
    ) -> ToolChatResponse:
        completion = self._client.chat.completions.create(
            model=self.model,
            messages=list(messages),
            tools=list(tools),
            tool_choice=tool_choice,
            temperature=temperature,
        )
        message = completion.choices[0].message
        tool_calls: list[ToolCall] = []
        for tool_call in message.tool_calls or []:
            raw_arguments = tool_call.function.arguments or "{}"
            try:
                arguments = json.loads(raw_arguments)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Tool call arguments are not valid JSON for {tool_call.function.name}: {raw_arguments}"
                ) from exc
            tool_calls.append(
                ToolCall(name=tool_call.function.name, arguments=arguments)
            )
        return ToolChatResponse(content=message.content or "", tool_calls=tool_calls)

    def complete(
        self,
        *,
        messages: Sequence[Mapping[str, str]],
        temperature: float = 0.0,
        response_format: Mapping[str, str] | None = None,
    ) -> str:
        request: dict[str, Any] = {
            "model": self.model,
            "messages": list(messages),
            "temperature": temperature,
        }
        if response_format is not None:
            request["response_format"] = dict(response_format)
        completion = self._client.chat.completions.create(**request)
        return completion.choices[0].message.content or ""

    def respond(
        self,
        *,
        messages: Sequence[Mapping[str, str]],
        temperature: float = 0.2,
    ) -> str:
        completion = self._client.chat.completions.create(
            model=self.model,
            messages=list(messages),
            temperature=temperature,
        )
        return completion.choices[0].message.content or ""

    def list_models(self) -> list[str]:
        return [model.id for model in self._client.models.list().data]
