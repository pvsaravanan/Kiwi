import pytest

from sentinel.config import DEFAULT_BASE_URL, load_settings


@pytest.fixture
def env(monkeypatch):
    monkeypatch.delenv("COGNEE_BASE_URL", raising=False)
    monkeypatch.delenv("SENTINEL_DATASET", raising=False)


def test_load_settings_defaults_base_url_when_unset(env):
    assert load_settings().base_url == DEFAULT_BASE_URL


def test_load_settings_reads_env_and_strips_trailing_slash(env, monkeypatch):
    monkeypatch.setenv("COGNEE_BASE_URL", "http://localhost:9999/")
    assert load_settings().base_url == "http://localhost:9999"


def test_dataset_defaults_to_sentinel(env):
    assert load_settings().dataset == "sentinel"


def test_dataset_reads_env(env, monkeypatch):
    monkeypatch.setenv("SENTINEL_DATASET", "other")
    assert load_settings().dataset == "other"
