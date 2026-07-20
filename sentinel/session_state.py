import json
import logging
import os
import stat

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

STATE_FILE = "kiwi_session_state.json"
KEY_FILE = "kiwi_secret.key"

_DEFAULT_STATE = {
    "last_failures": [],
    "failure_counts": {},
    "session_log": []
}


def _restrict_permissions(path: str):
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def _load_or_create_key() -> bytes:
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "rb") as f:
            return f.read()
    key = Fernet.generate_key()
    with open(KEY_FILE, "wb") as f:
        f.write(key)
    _restrict_permissions(KEY_FILE)
    return key


def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return dict(_DEFAULT_STATE)
    try:
        with open(STATE_FILE, "rb") as f:
            raw = f.read()
        try:
            data = Fernet(_load_or_create_key()).decrypt(raw)
        except InvalidToken:
            # Legacy plaintext state file written before encryption-at-rest was added.
            data = raw
        return json.loads(data)
    except Exception:
        # Corrupt/unreadable state file: log it and recover with a fresh
        # session rather than crashing every endpoint that reads state.
        logger.exception("Failed to load %s; starting from a fresh session state.", STATE_FILE)
        return dict(_DEFAULT_STATE)


def save_state(state: dict):
    """Persist session state. Raises on failure so callers (and their
    HTTP error handling) know the write did not actually happen, instead
    of silently reporting success while nothing was saved."""
    payload = json.dumps(state).encode("utf-8")
    token = Fernet(_load_or_create_key()).encrypt(payload)
    with open(STATE_FILE, "wb") as f:
        f.write(token)
    _restrict_permissions(STATE_FILE)
