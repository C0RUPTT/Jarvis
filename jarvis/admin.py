"""Server admin from Telegram, so you never need the terminal:

    /status   health: memory, disk, uptime, Claude login, jobs, version
    /update   pull the latest Jarvis code, install packages, restart
    /restart  restart Jarvis (systemd brings it straight back)
    /logs     the last lines of Jarvis's log
    /help     list of commands
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(cmd: list[str], timeout: int = 300) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def _restart_soon(delay: float = 2.0) -> None:
    """Exit so systemd (Restart=always) starts a fresh Jarvis. Delay lets the reply go out first."""
    threading.Timer(delay, lambda: os._exit(0)).start()


def status(config, jobs) -> str:
    lines = []
    try:
        import psutil

        vm, sw = psutil.virtual_memory(), psutil.swap_memory()
        du = psutil.disk_usage(str(Path.home()))
        up = (time.time() - psutil.boot_time()) / 3600
        lines += [
            f"Memory: {vm.used / 1e9:.2f} of {vm.total / 1e9:.1f} GB used, swap {sw.used / 1e9:.2f} GB",
            f"Disk: {du.free / 1e9:.0f} GB free",
            f"Server up {up:.0f} h",
        ]
    except ImportError:
        pass
    claude = shutil.which("claude")
    if claude:
        _, out = _run([claude, "auth", "status"], timeout=30)
        lines.append("Claude login: " + ("OK" if '"loggedIn": true' in out else "NOT logged in. Ask me how to fix it"))
    if jobs is not None:
        active = [j for j in jobs.jobs.values() if j.status in {"running", "queued"}]
        lines.append(f"Jobs: {len(active)} active, {len(jobs.jobs)} total")
    _, rev = _run(["git", "log", "-1", "--format=%h %cr"], timeout=10)
    lines.append(f"Version: {rev}")
    return "Jarvis status\n" + "\n".join(lines)


def update() -> str:
    code, out = _run(["git", "pull", "--ff-only"], timeout=120)
    if code != 0:
        return f"Update failed at git pull:\n{out[-800:]}"
    if "Already up to date" in out:
        return "Already up to date."
    reqs = ROOT / ("requirements-server.txt" if (ROOT / "requirements-server.txt").exists() else "requirements.txt")
    code, pip_out = _run([sys.executable, "-m", "pip", "install", "-q", "-r", str(reqs)], timeout=900)
    if code != 0:
        return f"Code updated, but installing packages failed:\n{pip_out[-800:]}"
    _restart_soon()
    return "Updated. Restarting now; I'll be back in about 10 seconds."


def logs() -> str:
    for cmd in (["journalctl", "-u", "jarvis", "-n", "40", "--no-pager", "-o", "cat"],
                ["sudo", "-n", "journalctl", "-u", "jarvis", "-n", "40", "--no-pager", "-o", "cat"]):
        code, out = _run(cmd, timeout=20)
        if code == 0 and out:
            return out[-3500:]
    return "Couldn't read the log (no permission)."


def commands(config, jobs) -> dict:
    return {
        "status": lambda: status(config, jobs),
        "update": update,
        "restart": lambda: (_restart_soon(), "Restarting; back in about 10 seconds.")[1],
        "logs": logs,
        "help": lambda: __doc__.strip(),
    }
