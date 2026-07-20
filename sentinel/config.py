import os
from dataclasses import dataclass
from dotenv import load_dotenv

import glob

# Dynamically discover all .env files and load them in priority order
env_files = [f for f in glob.glob(".env*") if not f.endswith(".example")]
def get_priority(filename):
    if filename == ".env.local":
        return 0
    if filename.endswith(".local"):
        return 1
    if filename == ".env":
        return 3
    return 2

env_files.sort(key=get_priority)
for f in env_files:
    if os.path.isfile(f):
        load_dotenv(f)


@dataclass(frozen=True)
class Settings:
    base_url: str
    api_key: str
    tenant_id: str
    dataset: str


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def load_settings() -> Settings:
    if "PYTEST_CURRENT_TEST" not in os.environ:
        from sentinel.session_state import load_state
        state = load_state()
        if state.get("is_logged_in") and state.get("base_url") and state.get("api_key") and state.get("tenant_id"):
            return Settings(
                base_url=state["base_url"].rstrip("/"),
                api_key=state["api_key"],
                tenant_id=state["tenant_id"],
                dataset=os.environ.get("SENTINEL_DATASET", "sentinel"),
            )

    return Settings(
        base_url=_require("COGNEE_BASE_URL").rstrip("/"),
        api_key=_require("COGNEE_API_KEY"),
        tenant_id=_require("COGNEE_TENANT_ID"),
        dataset=os.environ.get("SENTINEL_DATASET", "sentinel"),
    )


def auth_headers(settings: Settings) -> dict[str, str]:
    return {"X-Api-Key": settings.api_key, "X-Tenant-Id": settings.tenant_id}
