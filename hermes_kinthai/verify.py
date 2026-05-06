"""Verify that agents are online on KinthAI after installation."""

import time
import urllib.error

from . import api


def wait_for_agents(agents: list[dict], timeout: float = 45.0) -> dict[str, bool]:
    """Poll KinthAI until all agents are online or timeout is reached.

    agents: list of {id, api_key}
    Returns: {agent_id: True/False}
    """
    results = {a["id"]: False for a in agents}
    pending = list(agents)
    deadline = time.monotonic() + timeout

    while pending and time.monotonic() < deadline:
        still_pending = []
        for agent in pending:
            try:
                info = api.get_agent_status(agent["api_key"])
                if info.get("online") or info.get("status") == "online":
                    results[agent["id"]] = True
                    continue
            except Exception:
                pass
            still_pending.append(agent)
        pending = still_pending
        if pending:
            time.sleep(3)

    return results
