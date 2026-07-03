import pytest

from sentinel.config import Settings, auth_headers, load_settings


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("COGNEE_BASE_URL", "https://tenant-x.aws.cognee.ai/")
    monkeypatch.setenv("COGNEE_API_KEY", "key123")
    monkeypatch.setenv("COGNEE_TENANT_ID", "tid-1")
    monkeypatch.delenv("SENTINEL_DATASET", raising=False)


def test_load_settings_reads_env_and_strips_trailing_slash(env):
    s = load_settings()
    assert s.base_url == "https://tenant-x.aws.cognee.ai"
    assert s.api_key == "key123"
    assert s.tenant_id == "tid-1"


def test_dataset_defaults_to_sentinel(env):
    assert load_settings().dataset == "sentinel"


def test_dataset_reads_env(env, monkeypatch):
    monkeypatch.setenv("SENTINEL_DATASET", "other")
    assert load_settings().dataset == "other"


def test_missing_var_raises_with_name(env, monkeypatch):
    monkeypatch.delenv("COGNEE_API_KEY")
    with pytest.raises(RuntimeError, match="COGNEE_API_KEY"):
        load_settings()


def test_auth_headers(env):
    h = auth_headers(load_settings())
    assert h == {"X-Api-Key": "key123", "X-Tenant-Id": "tid-1"}
