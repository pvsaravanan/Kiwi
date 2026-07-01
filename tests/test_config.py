import importlib
import pytest

def test_dataset_name_defaults_to_sentinel(monkeypatch):
    monkeypatch.delenv("SENTINEL_DATASET", raising=False)
    import sentinel.config as cfg
    importlib.reload(cfg)
    assert cfg.DATASET_NAME == "sentinel"

def test_dataset_name_reads_from_env(monkeypatch):
    monkeypatch.setenv("SENTINEL_DATASET", "my-project")
    import sentinel.config as cfg
    importlib.reload(cfg)
    assert cfg.DATASET_NAME == "my-project"
