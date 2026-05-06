"""hermes-kinthai CLI — install, update, uninstall, status."""

from __future__ import annotations

import sys
import urllib.error

from . import api, install, tokens, verify
from .verify import UNVERIFIABLE
from .discover import discover_profiles, get_hermes_pip
from .machine_id import get_machine_id


def main() -> None:
    args = sys.argv[1:]
    if not args:
        _print_usage()
        sys.exit(1)

    cmd = args[0]
    if cmd in ("-h", "--help", "help"):
        _print_usage()
    elif cmd == "update":
        _cmd_update()
    elif cmd == "uninstall":
        _cmd_uninstall()
    elif cmd == "status":
        _cmd_status()
    elif not cmd.startswith("-"):
        _cmd_install(cmd)
    else:
        _print_usage()
        sys.exit(1)


# ── Commands ──────────────────────────────────────────────────────────────────

def _cmd_install(email: str) -> None:
    print()
    _step(1, 5, "Discovering Hermes profiles...")
    profiles = discover_profiles()
    if not profiles:
        _die("No active Hermes profiles found. "
             "Check that hermes-* systemd services are running.")
    for p in profiles:
        print(f"      → {p['id']:30s}  ({p['hermes_home']})")
    print(f"      → found {len(profiles)} profile(s)")

    _step(2, 5, "Generating machine identity...")
    machine_id = get_machine_id()
    print(f"      → machine-id: {machine_id[:16]}...")

    _step(3, 5, "Registering agents with KinthAI...")
    state = tokens.load()
    state["_email"] = email
    state["_machine_id"] = machine_id
    state.setdefault("_agents", [])

    registered = []
    for p in profiles:
        agent_id = p["id"]
        print(f"      → {agent_id} ...", end=" ", flush=True)
        try:
            resp = api.register_agent(
                email=email,
                machine_id=machine_id,
                agent_id=agent_id,
                agent_name=agent_id,
            )
            api_key = resp.get("api_key") or resp.get("token", "")
            kk_agent_id = resp.get("kk_agent_id") or resp.get("agent_id") or resp.get("id", "")
            state[agent_id] = {"api_key": api_key, "kk_agent_id": kk_agent_id}
            # Update _agents list (idempotent)
            state["_agents"] = [
                a for a in state["_agents"] if a["id"] != agent_id
            ]
            state["_agents"].append({
                "id": agent_id,
                "hermes_home": p["hermes_home"],
                "systemd_service": p["systemd_service"],
            })
            print("✓")
            registered.append({**p, "api_key": api_key})
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            print(f"✗  ({e.code}: {body[:80]})")
        except Exception as e:
            print(f"✗  ({e})")

    tokens.save(state)
    print(f"      → saved to {tokens.kinthai_home() / '.kinthai.json'}")

    if not registered:
        _die("No agents were registered. Aborting.")

    _step(4, 5, "Installing plugin + enabling per-profile...")
    pip = get_hermes_pip()
    if not pip:
        _die("Cannot locate Hermes venv pip. "
             "Is /home/hermes/.local/bin/hermes a symlink to the venv binary?")
    print(f"      → pip install hermes-kinthai ({pip}) ...", end=" ", flush=True)
    try:
        install.install_to_hermes_venv(pip)
        print("✓")
    except Exception as e:
        _die(f"pip install failed: {e}")

    for p in registered:
        agent_id = p["id"]
        api_key = p["api_key"]
        print(f"      → configuring {agent_id} ...", end=" ", flush=True)
        try:
            install.configure_profile(p["hermes_home"], api_key)
            print("✓")
        except Exception as e:
            print(f"✗  ({e})")

    services = [p["systemd_service"] for p in registered]
    print(f"      → restarting {', '.join(services)} ...")
    for svc in services:
        try:
            install.restart_service(svc)
            print(f"        {svc} ✓")
        except Exception as e:
            print(f"        {svc} ✗  ({e})")

    _step(5, 5, "Verifying connections...")
    agent_creds = [
        {"id": p["id"], "api_key": p["api_key"]} for p in registered
    ]
    results = verify.wait_for_agents(agent_creds, timeout=45.0)
    unverified = False
    failed = False
    for agent_id, status in results.items():
        if status is True:
            mark = "✓ online"
        elif status == UNVERIFIABLE:
            mark = "? connected (online status not yet in API)"
            unverified = True
        else:
            mark = "✗ timeout — check service logs"
            failed = True
        print(f"      → {agent_id}: {mark}")

    print()
    mentions = "  ".join(f"@{p['id']}" for p in registered)
    if failed:
        print("  Some agents did not come online. "
              "Run `journalctl -u hermes-lead -n 50` to investigate.")
    else:
        print(f"  Done! Mention your agents:  {mentions}")
    if unverified:
        print("  Note: online confirmation requires backend to add "
              "`online` field to GET /api/v1/users/me")
    print()


def _cmd_update() -> None:
    print()
    _step(1, 2, "Updating hermes-kinthai in Hermes venv...")
    pip = get_hermes_pip()
    if not pip:
        _die("Cannot locate Hermes venv pip.")
    try:
        install.install_to_hermes_venv(pip)
        print("      → updated ✓")
    except Exception as e:
        _die(f"pip install --upgrade failed: {e}")

    _step(2, 2, "Restarting services...")
    state = tokens.load()
    for a in state.get("_agents", []):
        svc = a["systemd_service"]
        try:
            install.restart_service(svc)
            print(f"      → {svc} ✓")
        except Exception as e:
            print(f"      → {svc} ✗  ({e})")
    print()


def _cmd_uninstall() -> None:
    state = tokens.load()
    agents = state.get("_agents", [])

    print()
    _step(1, 3, "Removing per-profile configuration...")
    for a in agents:
        print(f"      → {a['id']} ...", end=" ", flush=True)
        try:
            install.unconfigure_profile(a["hermes_home"])
            print("✓")
        except Exception as e:
            print(f"✗  ({e})")

    _step(2, 3, "Restarting services...")
    for a in agents:
        svc = a["systemd_service"]
        try:
            install.restart_service(svc)
            print(f"      → {svc} ✓")
        except Exception as e:
            print(f"      → {svc} ✗  ({e})")

    _step(3, 3, "Uninstalling hermes-kinthai from Hermes venv...")
    pip = get_hermes_pip()
    if pip:
        try:
            install.uninstall_from_hermes_venv(pip)
            print("      → uninstalled ✓")
        except Exception as e:
            print(f"      → ✗  ({e})")
    else:
        print("      → Hermes pip not found, skipping venv uninstall")
    print()


def _cmd_status() -> None:
    state = tokens.load()
    agents = state.get("_agents", [])
    if not agents:
        print("No agents registered. Run: hermes-kinthai <email>")
        return

    print()
    print(f"  Registered agents ({len(agents)}):")
    for a in agents:
        agent_id = a["id"]
        creds = state.get(agent_id, {})
        api_key = creds.get("api_key", "")
        if not api_key:
            print(f"    {agent_id}: no api_key")
            continue
        try:
            info = api.get_agent_status(api_key)
            if "online" in info or "status" in info:
                online = info.get("online") or info.get("status") == "online"
                mark = "● online" if online else "○ offline"
            else:
                mark = "? (online status not in API)"
        except Exception as e:
            mark = f"? ({e})"
        print(f"    {agent_id}: {mark}")
    print()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _step(n: int, total: int, msg: str) -> None:
    print(f"[{n}/{total}] {msg}")


def _die(msg: str) -> None:
    print(f"\n  Error: {msg}", file=sys.stderr)
    sys.exit(1)


def _print_usage() -> None:
    print(
        "Usage:\n"
        "  hermes-kinthai <email>   Install and connect all Hermes agents\n"
        "  hermes-kinthai update    Update plugin in Hermes venv + restart\n"
        "  hermes-kinthai uninstall Remove plugin and configuration\n"
        "  hermes-kinthai status    Show agent online status\n"
    )
