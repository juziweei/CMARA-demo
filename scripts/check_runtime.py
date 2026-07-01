from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.action.llm_client import OpenAIToolClient
from src.config import DemoConfig


def _exists(path_text: str) -> bool:
    return Path(path_text).exists()


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def main() -> None:
    settings = DemoConfig()
    qwen_path = settings.resolve_qwen_model_path()
    embedding_path = settings.resolve_embedding_model_path()
    llmlingua_path = settings.resolve_llmlingua_model_path()
    print("Runtime config:")
    print(f"  LLM base URL: {settings.llm_base_url}")
    print(f"  LLM model: {settings.llm_model}")
    print(f"  Qwen path: {qwen_path}")
    print(f"  Qwen exists: {_exists(qwen_path)}")
    print(f"  Embedding path: {embedding_path or '<unresolved>'}")
    print(f"  Embedding exists: {_exists(embedding_path) if embedding_path else False}")
    print(f"  LLMLingua path/id: {llmlingua_path}")
    print(f"  LLMLingua local path exists: {_exists(llmlingua_path)}")
    print(f"  llmlingua package installed: {_module_available('llmlingua')}")
    print(f"  Preferences path: {settings.preferences_path}")
    print(f"  Qdrant path: {settings.qdrant_path}")

    client = OpenAIToolClient(
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        api_key=settings.llm_api_key,
    )
    try:
        models = client.list_models()
    except Exception as exc:  # pragma: no cover - live runtime path
        print(f"  LLM connection check failed: {exc}")
        return
    print("Models served:")
    for model in models:
        print(f"  - {model}")


if __name__ == "__main__":
    main()
