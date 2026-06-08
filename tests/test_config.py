from __future__ import annotations

from src.config import DemoConfig, LLMLINGUA_MODEL_ID


def test_build_lightmem_config_enables_llmlingua_precompression(tmp_path) -> None:
    embedding_dir = tmp_path / "embedding"
    llmlingua_dir = tmp_path / "llmlingua"
    embedding_dir.mkdir()
    llmlingua_dir.mkdir()
    (embedding_dir / "config.json").write_text("{}", encoding="utf-8")
    (llmlingua_dir / "config.json").write_text("{}", encoding="utf-8")

    settings = DemoConfig(
        embedding_model_path=str(embedding_dir),
        llmlingua_model_path=str(llmlingua_dir),
        preferences_path=tmp_path / "preferences.json",
        qdrant_path=tmp_path / "qdrant",
        history_db_path=tmp_path / "history.db",
    )

    config = settings.build_lightmem_config()

    assert config["pre_compress"] is True
    assert config["extraction_mode"] == "flat"
    assert config["precomp_topic_shared"] is True
    assert config["topic_segment"] is True
    assert config["topic_segmenter"]["model_name"] == "llmlingua-2"
    assert config["pre_compressor"]["configs"]["llmlingua_config"]["model_name"] == str(
        llmlingua_dir
    )


def test_build_lightmem_config_supports_event_mode_without_precompression(tmp_path) -> None:
    embedding_dir = tmp_path / "embedding"
    llmlingua_dir = tmp_path / "llmlingua"
    embedding_dir.mkdir()
    llmlingua_dir.mkdir()
    (embedding_dir / "config.json").write_text("{}", encoding="utf-8")
    (llmlingua_dir / "config.json").write_text("{}", encoding="utf-8")

    settings = DemoConfig(
        embedding_model_path=str(embedding_dir),
        llmlingua_model_path=str(llmlingua_dir),
        preferences_path=tmp_path / "preferences.json",
        qdrant_path=tmp_path / "qdrant",
        history_db_path=tmp_path / "history.db",
        lightmem_extraction_mode="event",
        lightmem_pre_compress=False,
    )

    config = settings.build_lightmem_config()

    assert config["pre_compress"] is False
    assert config["extraction_mode"] == "event"
    assert config["precomp_topic_shared"] is False


def test_resolve_llmlingua_model_path_falls_back_to_model_id_when_local_path_missing() -> None:
    settings = DemoConfig(llmlingua_model_path=LLMLINGUA_MODEL_ID)

    assert settings.resolve_llmlingua_model_path() == LLMLINGUA_MODEL_ID
