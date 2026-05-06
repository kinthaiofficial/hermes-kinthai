"""KinthAI REST API client (stdlib urllib only, no external deps)."""

import json
import urllib.error
import urllib.request
from typing import Any

API_BASE = "https://kinthai.ai"


def register_agent(
    email: str,
    machine_id: str,
    agent_id: str,
    agent_name: str,
) -> dict:
    return _post(
        "/api/v1/register",
        {
            "email": email,
            "openclaw_machine_id": machine_id,
            "openclaw_agent_id": agent_id,
        },
    )


def get_me(api_key: str) -> dict:
    return _get("/api/v1/users/me", api_key)


def get_agent_status(api_key: str) -> dict:
    return _get("/api/v1/users/me", api_key)


def _post(path: str, data: dict) -> dict:
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        API_BASE + path,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 409:
            return json.loads(e.read())
        raise


def _get(path: str, api_key: str) -> dict:
    req = urllib.request.Request(
        API_BASE + path,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())
