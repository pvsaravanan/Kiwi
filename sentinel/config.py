import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


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
    return Settings(
        base_url=_require("COGNEE_BASE_URL").rstrip("/"),
        api_key=_require("COGNEE_API_KEY"),
        tenant_id=_require("COGNEE_TENANT_ID"),
        dataset=os.environ.get("SENTINEL_DATASET", "sentinel"),
    )


def auth_headers(settings: Settings) -> dict[str, str]:
    return {"X-Api-Key": settings.api_key, "X-Tenant-Id": settings.tenant_id}
