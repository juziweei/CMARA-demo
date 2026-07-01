from __future__ import annotations

from typing import Any, Callable, Mapping

TOOLS_META: dict[str, dict[str, Any]] = {
    "set_ac_temperature": {"cost": "low", "reversible": True},
    "set_seat_heating": {"cost": "low", "reversible": True},
    "ask_user": {"cost": "zero", "reversible": True},
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


TOOL_EXECUTORS: dict[str, Callable[..., dict[str, Any]]] = {
    "set_ac_temperature": set_ac_temperature,
    "set_seat_heating": set_seat_heating,
    "ask_user": ask_user,
}


def run_tool(name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
    if name not in TOOL_EXECUTORS:
        raise KeyError(f"Unknown tool: {name}")
    return TOOL_EXECUTORS[name](**dict(arguments))
