"""Discover active Hermes profiles via systemd."""

import os
import re
import subprocess
from typing import Optional


def discover_profiles() -> list[dict]:
    """Return list of active Hermes profile dicts.

    Each dict: {id, hermes_home, systemd_service, webhook_port}
    """
    try:
        result = subprocess.run(
            ["systemctl", "list-units", "hermes-*", "--no-legend", "--state=active"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []

    profiles = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if not parts:
            continue
        unit = parts[0]
        if not unit.endswith(".service"):
            continue

        try:
            cat = subprocess.run(
                ["systemctl", "cat", unit],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except subprocess.TimeoutExpired:
            continue

        exec_match = re.search(r"ExecStart=(.+)", cat.stdout)
        if not exec_match:
            continue
        cmd = exec_match.group(1).strip()

        # Detect profile from command line
        if "-p" not in cmd:
            # Default profile (hermes-lead)
            hermes_home = _hermes_user_home(".hermes")
            profile_name = "lead"
        else:
            p_match = re.search(r"-p\s+(\S+)", cmd)
            if not p_match:
                continue
            profile_name = p_match.group(1)
            hermes_home = _hermes_user_home(f".hermes/profiles/{profile_name}")

        port = _read_env_var(os.path.join(hermes_home, ".env"), "WEBHOOK_PORT")

        profiles.append(
            {
                "id": f"hermes-{profile_name}",
                "hermes_home": hermes_home,
                "systemd_service": unit,
                "webhook_port": int(port) if port and port.isdigit() else None,
            }
        )

    return profiles


def _hermes_user_home(rel: str) -> str:
    """Expand path relative to the hermes user's home directory."""
    try:
        import pwd
        hermes_pw = pwd.getpwnam("hermes")
        return os.path.join(hermes_pw.pw_dir, rel)
    except (KeyError, ImportError):
        return os.path.expanduser(f"~/{rel}")


def _read_env_var(env_file: str, key: str) -> Optional[str]:
    try:
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line.startswith(f"{key}="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return None


def get_hermes_pip() -> Optional[str]:
    """Resolve the pip binary inside the Hermes venv.

    Follows the symlink /home/hermes/.local/bin/hermes → venv/bin/hermes.
    """
    link = "/home/hermes/.local/bin/hermes"
    if not os.path.islink(link):
        return None
    try:
        real = os.readlink(link)
        if not os.path.isabs(real):
            real = os.path.join(os.path.dirname(link), real)
        pip = os.path.join(os.path.dirname(real), "pip")
        return pip if os.path.isfile(pip) else None
    except OSError:
        return None
