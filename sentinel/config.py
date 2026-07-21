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


# Self-hosted Cognee's default port (8000) collides with Kiwi's own backend,
# so docker-compose.cognee.yml maps it to the host at 8010 instead.
DEFAULT_BASE_URL = "http://localhost:8010"


@dataclass(frozen=True)
class Settings:
    base_url: str
    dataset: str


def load_settings() -> Settings:
    base_url = os.environ.get("COGNEE_BASE_URL", "").strip() or DEFAULT_BASE_URL
    return Settings(
        base_url=base_url.rstrip("/"),
        dataset=os.environ.get("SENTINEL_DATASET", "sentinel"),
    )
