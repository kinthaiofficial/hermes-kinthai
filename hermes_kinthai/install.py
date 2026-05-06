"""Install hermes-kinthai into Hermes venv and configure each profile."""

import os
import subprocess

import yaml


def install_to_hermes_venv(pip: str) -> None:
    """Install (or upgrade) hermes-kinthai into the Hermes venv."""
    subprocess.run([pip, "install", "--upgrade", "hermes-kinthai"], check=True)


def configure_profile(hermes_home: str, api_key: str) -> None:
    """Write KINTHAI_TOKEN to .env and enable the kinthai plugin in config.yaml."""
    _append_env(os.path.join(hermes_home, ".env"), "KINTHAI_TOKEN", api_key)
    _append_env(
        os.path.join(hermes_home, ".env"),
        "KINTHAI_API_BASE",
        "https://kinthai.ai",
    )
    _enable_plugin(os.path.join(hermes_home, "config.yaml"), "kinthai")


def unconfigure_profile(hermes_home: str) -> None:
    """Remove KINTHAI_TOKEN from .env and disable kinthai plugin in config.yaml."""
    _remove_env_keys(os.path.join(hermes_home, ".env"), {"KINTHAI_TOKEN", "KINTHAI_API_BASE"})
    _disable_plugin(os.path.join(hermes_home, "config.yaml"), "kinthai")


def restart_service(unit: str) -> None:
    subprocess.run(["sudo", "systemctl", "restart", unit], check=True)


def uninstall_from_hermes_venv(pip: str) -> None:
    subprocess.run([pip, "uninstall", "-y", "hermes-kinthai"], check=True)


# ── helpers ──────────────────────────────────────────────────────────────────

def _append_env(path: str, key: str, value: str) -> None:
    """Append KEY=value to .env file if not already present (idempotent)."""
    try:
        content = open(path).read()
    except OSError:
        content = ""
    line = f"{key}={value}"
    # Check any existing value for this key
    for existing in content.splitlines():
        if existing.strip().startswith(f"{key}="):
            return  # already set (any value)
    with open(path, "a") as f:
        if content and not content.endswith("\n"):
            f.write("\n")
        f.write(f"{line}\n")


def _remove_env_keys(path: str, keys: set) -> None:
    try:
        lines = open(path).readlines()
    except OSError:
        return
    filtered = [
        ln for ln in lines
        if not any(ln.strip().startswith(f"{k}=") for k in keys)
    ]
    with open(path, "w") as f:
        f.writelines(filtered)


def _enable_plugin(path: str, name: str) -> None:
    """Add plugin name to plugins.enabled in config.yaml (idempotent)."""
    try:
        with open(path) as f:
            cfg = yaml.safe_load(f) or {}
    except OSError:
        cfg = {}
    plugins = cfg.setdefault("plugins", {})
    enabled = plugins.setdefault("enabled", [])
    if name not in enabled:
        enabled.append(name)
        _write_yaml(path, cfg)


def _disable_plugin(path: str, name: str) -> None:
    try:
        with open(path) as f:
            cfg = yaml.safe_load(f) or {}
    except OSError:
        return
    enabled = cfg.get("plugins", {}).get("enabled", [])
    if name in enabled:
        enabled.remove(name)
        _write_yaml(path, cfg)


def _write_yaml(path: str, data: dict) -> None:
    with open(path, "w") as f:
        yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True)
