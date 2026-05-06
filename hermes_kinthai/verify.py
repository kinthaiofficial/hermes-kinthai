"""Verify that agents are online on KinthAI after installation."""

import time
import urllib.error

from . import api

# Sentinel: API responded successfully but has no online-status field.
# Distinct from False (explicitly offline) so callers can show a helpful message.
UNVERIFIABLE = "unverifiable"


def wait_for_agents(
    agents: list[dict], timeout: float = 45.0
) -> dict[str, "bool | str"]:
    """Poll KinthAI until all agents are online or timeout is reached.

    agents: list of {id, api_key}
    Returns: {agent_id: True | False | UNVERIFIABLE}
      - True        agent is confirmed online
      - False       timed out (agent did not come online within timeout)
      - UNVERIFIABLE backend responded but has no online-status field yet
    """
    results: dict[str, bool | str] = {a["id"]: False for a in agents}
    pending = list(agents)
    deadline = time.monotonic() + timeout

    while pending and time.monotonic() < deadline:
        still_pending = []
        for agent in pending:
            try:
                info = api.get_agent_status(agent["api_key"])
            except Exception:
                still_pending.append(agent)
                continue

            if "online" in info or "status" in info:
                # Backend supports online status — check the value
                if info.get("online") or info.get("status") == "online":
                    results[agent["id"]] = True
                else:
                    still_pending.append(agent)
            else:
                # Backend responded but doesn't expose online status yet
                results[agent["id"]] = UNVERIFIABLE

        pending = still_pending
        if pending:
            time.sleep(3)

    return results
