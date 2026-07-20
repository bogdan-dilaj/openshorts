import json

from whisper_runtime import _sync_model_support_files


def test_sync_model_support_files_repairs_preprocessor_metadata(tmp_path):
    source_dir = tmp_path / "source"
    target_dir = tmp_path / "converted"
    source_dir.mkdir()
    target_dir.mkdir()

    preprocessor = {"feature_size": 128, "sampling_rate": 16000}
    (source_dir / "preprocessor_config.json").write_text(
        json.dumps(preprocessor),
        encoding="utf-8",
    )
    (source_dir / "tokenizer.json").write_text('{"source": true}', encoding="utf-8")
    (target_dir / "model.bin").write_bytes(b"converted-model")
    (target_dir / "config.json").write_text('{"ctranslate2": true}', encoding="utf-8")

    copied = _sync_model_support_files(str(source_dir), str(target_dir))

    assert copied == ["tokenizer.json", "preprocessor_config.json"]
    assert json.loads((target_dir / "preprocessor_config.json").read_text(encoding="utf-8")) == preprocessor
    assert json.loads((target_dir / "config.json").read_text(encoding="utf-8")) == {"ctranslate2": True}


def test_sync_model_support_files_keeps_matching_cached_file(tmp_path):
    source_dir = tmp_path / "source"
    target_dir = tmp_path / "converted"
    source_dir.mkdir()
    target_dir.mkdir()
    content = '{"feature_size": 128}'
    (source_dir / "preprocessor_config.json").write_text(content, encoding="utf-8")
    (target_dir / "preprocessor_config.json").write_text(content, encoding="utf-8")

    assert _sync_model_support_files(str(source_dir), str(target_dir)) == []
