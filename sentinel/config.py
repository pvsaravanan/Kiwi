import os
import cognee
from dotenv import load_dotenv

load_dotenv()

COGNEE_BASE_URL: str = os.environ["COGNEE_BASE_URL"]
COGNEE_API_KEY: str = os.environ["COGNEE_API_KEY"]
DATASET_NAME: str = os.getenv("SENTINEL_DATASET", "sentinel")

def setup_cognee() -> None:
    cognee.config.base_url = COGNEE_BASE_URL
    cognee.config.cognee_api_key = COGNEE_API_KEY
