from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LLMLINGUA_MODEL_ID = "microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank"


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


@dataclass
class DemoConfig:
    llm_base_url: str = os.getenv("DEMO_LLM_BASE_URL", "http://127.0.0.1:7200/v1")
    llm_model: str = os.getenv("DEMO_LLM_MODEL", "Qwen2.5-14B-Instruct")
    llm_api_key: str = os.getenv("DEMO_LLM_API_KEY", "EMPTY")
    qwen_model_path: str = os.getenv(
        "DEMO_QWEN_MODEL_PATH",
        "/data/cache/modelscope/hub/models/Qwen/Qwen2.5-14B-Instruct",
    )
    embedding_model_path: str = os.getenv("DEMO_EMBEDDING_MODEL_PATH", "")
    llmlingua_model_path: str = os.getenv(
        "DEMO_LLMLINGUA_MODEL_PATH", LLMLINGUA_MODEL_ID
    )
    llmlingua_device_map: str = os.getenv("DEMO_LLMLINGUA_DEVICE_MAP", "cuda")
    preferences_path: Path = Path(
        os.getenv("DEMO_PREFERENCES_PATH", "data/preferences.json")
    )
    qdrant_path: Path = Path(os.getenv("DEMO_QDRANT_PATH", "data/qdrant"))
    history_db_path: Path = Path(os.getenv("DEMO_HISTORY_DB_PATH", "data/history.db"))
    lightmem_collection: str = os.getenv(
        "DEMO_LIGHTMEM_COLLECTION", "vehicle_memory_demo"
    )
    lightmem_update: str = os.getenv("DEMO_LIGHTMEM_UPDATE", "offline")
    lightmem_extraction_mode: str = os.getenv(
        "DEMO_LIGHTMEM_EXTRACTION_MODE", "flat"
    )
    lightmem_pre_compress: bool = _env_flag("DEMO_LIGHTMEM_PRE_COMPRESS", True)
    lightmem_max_tokens: int = int(os.getenv("DEMO_LIGHTMEM_MAX_TOKENS", "512"))
    lightmem_num_gpu: int = int(os.getenv("DEMO_LIGHTMEM_NUM_GPU", "-1"))
    lightmem_extract_threshold: float = float(
        os.getenv("DEMO_LIGHTMEM_EXTRACT_THRESHOLD", "0.1")
    )
    lightmem_compress_rate: float = float(
        os.getenv("DEMO_LIGHTMEM_COMPRESS_RATE", "1.0")
    )

    def ensure_storage(self) -> None:
        self.preferences_path.parent.mkdir(parents=True, exist_ok=True)
        self.qdrant_path.mkdir(parents=True, exist_ok=True)
        self.history_db_path.parent.mkdir(parents=True, exist_ok=True)

    def resolve_qwen_model_path(self) -> str:
        candidates = [
            self.qwen_model_path,
            "/data/cache/modelscope/hub/models/Qwen/Qwen2.5-14B-Instruct",
            "/data/cache/modelscope/hub/models/Qwen/Qwen2.5-7B-Instruct",
        ]
        for candidate in candidates:
            if candidate and Path(candidate).exists():
                return candidate
        return self.qwen_model_path

    def resolve_embedding_model_path(self) -> str:
        resolved = _resolve_snapshot_path(
            configured_path=self.embedding_model_path,
            snapshot_roots=[
                Path(
                    "/data/cache/huggingface/hub/models--sentence-transformers--all-MiniLM-L6-v2/snapshots"
                ),
                Path.home()
                / ".cache/huggingface/hub/models--sentence-transformers--all-MiniLM-L6-v2/snapshots",
            ],
        )
        return resolved or self.embedding_model_path

    def resolve_llmlingua_model_path(self) -> str:
        resolved = _resolve_snapshot_path(
            configured_path=self.llmlingua_model_path,
            snapshot_roots=[
                Path(
                    "/data/cache/huggingface/hub/models--microsoft--llmlingua-2-bert-base-multilingual-cased-meetingbank/snapshots"
                ),
                Path.home()
                / ".cache/huggingface/hub/models--microsoft--llmlingua-2-bert-base-multilingual-cased-meetingbank/snapshots",
            ],
        )
        return resolved or self.llmlingua_model_path

    def build_lightmem_config(self) -> dict[str, Any]:
        embedding_model_path = self.resolve_embedding_model_path()
        llmlingua_model_path = self.resolve_llmlingua_model_path()
        self.ensure_storage()
        if not embedding_model_path:
            embedding_model_path = self._fallback_embedding_model_path()
        return {
            "pre_compress": self.lightmem_pre_compress,
            "pre_compressor": {
                "model_name": "llmlingua-2",
                "configs": {
                    "llmlingua_config": {
                        "model_name": llmlingua_model_path,
                        "device_map": self.llmlingua_device_map,
                        "use_llmlingua2": True,
                    },
                    "compress_config": {
                        "instruction": "",
                        "rate": self.lightmem_compress_rate,
                        "target_token": -1,
                    },
                },
            },
            "topic_segment": True,
            "precomp_topic_shared": self.lightmem_pre_compress,
            "topic_segmenter": {
                "model_name": "llmlingua-2",
                "configs": {
                    "model_name": llmlingua_model_path,
                    "device_map": self.llmlingua_device_map,
                },
            },
            "messages_use": "hybrid",
            "metadata_generate": True,
            "text_summary": True,
            "memory_manager": {
                "model_name": "vllm",
                "configs": {
                    "model": self.llm_model,
                    "api_key": self.llm_api_key,
                    "vllm_base_url": self.llm_base_url,
                    "max_tokens": self.lightmem_max_tokens,
                    "temperature": 0.0,
                },
            },
            "extract_threshold": self.lightmem_extract_threshold,
            "extraction_mode": self.lightmem_extraction_mode,
            "index_strategy": "embedding",
            "text_embedder": {
                "model_name": "huggingface",
                "configs": {
                    "model": embedding_model_path,
                    "embedding_dims": 384,
                    "model_kwargs": {"device": "cpu"},
                },
            },
            "embedding_retriever": {
                "model_name": "qdrant",
                "configs": {
                    "collection_name": self.lightmem_collection,
                    "embedding_model_dims": 384,
                    "path": str(self.qdrant_path),
                },
            },
            "retrieve_strategy": "embedding",
            "history_db_path": str(self.history_db_path),
            "update": self.lightmem_update,
        }

    def _fallback_embedding_model_path(self) -> str:
        return "sentence-transformers/all-MiniLM-L6-v2"


def _resolve_snapshot_path(
    *,
    configured_path: str,
    snapshot_roots: list[Path],
) -> str | None:
    if configured_path and Path(configured_path).exists():
        return configured_path
    for root in snapshot_roots:
        if not root.exists():
            continue
        candidates = sorted(path for path in root.iterdir() if path.is_dir())
        for candidate in reversed(candidates):
            if (candidate / "config.json").exists():
                return str(candidate)
    return None
