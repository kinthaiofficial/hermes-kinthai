"""Cross-platform machine identity for agent registration."""

import hashlib
import os
import re
import socket
import subprocess


def get_machine_id() -> str:
    """Return a stable machine identifier, preferring OS-native sources."""
    # Linux
    try:
        with open("/etc/machine-id") as f:
            mid = f.read().strip()
            if len(mid) >= 16:
                return mid
    except OSError:
        pass

    # macOS
    try:
        out = subprocess.check_output(
            ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            text=True,
            timeout=5,
        )
        m = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', out)
        if m:
            return m.group(1).replace("-", "").lower()
    except Exception:
        pass

    # Windows
    try:
        import winreg  # type: ignore[import]

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
        ) as key:
            val, _ = winreg.QueryValueEx(key, "MachineGuid")
            return val.replace("-", "").lower()
    except Exception:
        pass

    # Fallback: deterministic from hostname
    return hashlib.sha256(socket.gethostname().encode()).hexdigest()[:32]
