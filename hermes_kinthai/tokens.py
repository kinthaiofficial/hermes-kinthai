"""Read/write ~/.hermes-kinthai/.kinthai.json."""

import json
import os
from pathlib import Path
from typing import Any

_DEFAULT_HOME = Path.home() / ".hermes-kinthai"
_KINTHAI_HOME = Path(os.environ.get("HERMES_KINTHAI_HOME", str(_DEFAULT_HOME)))
_TOKENS_FILE = _KINTHAI_HOME / ".kinthai.json"


def load() -> dict:
    try:
        return json.loads(_TOKENS_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def save(data: dict) -> None:
    _KINTHAI_HOME.mkdir(parents=True, exist_ok=True)
    _TOKENS_FILE.write_text(json.dumps(data, indent=2))
    _TOKENS_FILE.chmod(0o600)


def get(key: str, default: Any = None) -> Any:
    return load().get(key, default)


def set_key(key: str, value: Any) -> None:
    data = load()
    data[key] = value
    save(data)


def kinthai_home() -> Path:
    return _KINTHAI_HOME
