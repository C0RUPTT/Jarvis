"""Server admin from Telegram, so you never need the terminal:

    /status   health: memory, disk, uptime, Claude login, jobs, version
    /update   pull the latest Jarvis code, install packages, restart
    /restart  restart Jarvis (systemd brings it straight back)
    /logs     the last lines of Jarvis's log
    /shortcut the exact links to paste into the iPhone Shortcuts
    /timezone set your time zone, e.g. /timezone America/New_York
    /city     your city for the morning weather, e.g. /city Dallas
    /backup   back up memory, reminders and projects to your private GitHub now (also nightly)
    /restore  bring a backup back onto a new server
    /notifysetup  public link so Claude Code can tell Jarvis when it's done
    /github <key> connect your GitHub so Jarvis can work on your projects
    /textsetup    spoken alerts by text message (see docs/SPOKEN_TEXTS.md); /texttest, /textalt, /textoff
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


def status(config, jobs, brain=None) -> str:
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
    connectors = getattr(brain, "connectors", None)
    if connectors is not None:
        lines.append("Connected apps: " + (", ".join(connectors) if connectors else
                                           "none yet (ask me anything once, then check again)"))
    if jobs is not None:
        active = [j for j in jobs.jobs.values() if j.status in {"running", "queued"}]
        lines.append(f"Jobs: {len(active)} active, {len(jobs.jobs)} total")
    _, rev = _run(["git", "log", "-1", "--format=%h %cr"], timeout=10)
    lines.append(f"Version: {rev}")
    return "Jarvis status\n" + "\n".join(lines)


def _head() -> str:
    return _run(["git", "rev-parse", "HEAD"], timeout=10)[1].strip()


FAILED_FILE = Path.home() / ".jarvis" / "failed-update"
UPDATE_NOTE = Path.home() / ".jarvis" / "just-updated"   # written before restarting; read after


def report_update(announce) -> None:
    """After restarting from an update: tell the user what's new (once)."""
    if UPDATE_NOTE.exists():
        changes = UPDATE_NOTE.read_text().strip()
        UPDATE_NOTE.unlink(missing_ok=True)
        announce("I'm back and updated, sir." + (f" What's new:\n{changes[:1500]}" if changes else ""))


def _upstream() -> str:
    return _run(["git", "rev-parse", "@{u}"], timeout=10)[1].strip()


def update_available() -> bool:
    code, _ = _run(["git", "fetch", "-q", "origin"], timeout=60)
    if code != 0:
        return False
    code, out = _run(["git", "rev-list", "--count", "HEAD..@{u}"], timeout=10)
    if not (code == 0 and out.strip().isdigit() and int(out.strip()) > 0):
        return False
    # Don't retry a version that already failed its checks; wait for a newer one.
    return not (FAILED_FILE.exists() and FAILED_FILE.read_text().strip() == _upstream())


def update() -> str:
    """Pull the latest code, install packages, check it imports cleanly, then restart.
    If the new code is broken, roll back to the previous version and say so."""
    before = _head()
    code, out = _run(["git", "pull", "--ff-only"], timeout=120)
    if code != 0:
        return f"Update failed at git pull:\n{out[-800:]}"
    if "Already up to date" in out:
        return "Already up to date."
    _, changes = _run(["git", "log", "--format=- %s", f"{before}..HEAD"], timeout=10)
    reqs = ROOT / ("requirements-server.txt" if (ROOT / "requirements-server.txt").exists() else "requirements.txt")
    code, pip_out = _run([sys.executable, "-m", "pip", "install", "-q", "-r", str(reqs)], timeout=900)
    if code == 0:   # smoke test: the new code must at least import
        code, pip_out = _run([sys.executable, "-c", "import jarvis.server, jarvis.runtime, jarvis.telegram"],
                             timeout=120)
    if code != 0:
        try:
            FAILED_FILE.parent.mkdir(parents=True, exist_ok=True)
            FAILED_FILE.write_text(_head())
        except OSError:
            pass
        _run(["git", "reset", "--hard", before], timeout=30)
        return f"The update failed its checks, so I rolled back to the previous version.\n{pip_out[-600:]}"
    _restart_soon()
    return f"Updated. Restarting now; back in about 10 seconds.\nWhat's new:\n{changes[:1500]}"


def auto_update_loop(rt, every_minutes: int = 15) -> None:
    """Check for new code regularly and install it when Jarvis is idle."""
    def busy() -> bool:
        lock = getattr(rt.brain, "lock", None)
        if lock is not None and lock.locked():
            return True
        jobs = rt.jobs.jobs.values() if rt.jobs is not None else []
        return any(j.status == "running" for j in jobs)

    def loop():
        time.sleep(120)   # let startup finish
        while True:
            try:
                if update_available() and not busy():
                    result = update()
                    if result.startswith("Updated"):
                        UPDATE_NOTE.parent.mkdir(parents=True, exist_ok=True)
                        UPDATE_NOTE.write_text(result.split("What's new:", 1)[-1].strip())
                    elif "rolled back" in result:
                        rt.announcer.announce(result, reply=True)
            except Exception as e:  # noqa: BLE001 - never let the updater take Jarvis down
                print(f"[auto-update] {e}")
            time.sleep(every_minutes * 60)

    threading.Thread(target=loop, daemon=True, name="jarvis-autoupdate").start()


def logs() -> str:
    for cmd in (["journalctl", "-u", "jarvis", "-n", "40", "--no-pager", "-o", "cat"],
                ["sudo", "-n", "journalctl", "-u", "jarvis", "-n", "40", "--no-pager", "-o", "cat"]):
        code, out = _run(cmd, timeout=20)
        if code == 0 and out:
            return out[-3500:]
    return "Couldn't read the log (no permission)."


_host_cache: list = []


def public_host() -> str:
    """This server's private Tailscale name (e.g. jarvis.tail1234.ts.net), cached."""
    if _host_cache:
        return _host_cache[0]
    import json

    tailscale = shutil.which("tailscale")
    if tailscale:
        _, out = _run([tailscale, "status", "--json"], timeout=15)
        try:
            _host_cache.append(json.loads(out)["Self"]["DNSName"].rstrip("."))
            return _host_cache[0]
        except (ValueError, KeyError):
            pass
    return ""


def shortcut(config) -> str:
    """Ready-to-paste links (token included) for the Siri Shortcut and the alarm automation."""
    import json

    host = "<your-server>.ts.net"
    tailscale = shutil.which("tailscale")
    if tailscale:
        code, out = _run([tailscale, "status", "--json"], timeout=15)
        try:
            host = json.loads(out)["Self"]["DNSName"].rstrip(".")
        except (ValueError, KeyError):
            pass
    base = f"https://{host}"
    return (
        "Siri Shortcut (3 actions):\n"
        "1. Dictate Text\n"
        "2. Get Contents of URL - paste the link below, Method POST, Request Body JSON, "
        "add a Text field: key  text  value  Dictated Text\n"
        "3. Speak Text - Contents of URL\n\n"
        f"{base}/api/ask?format=text&token={config.token}\n\n"
        "Alarm automation (Alarm > Is Stopped > Run Immediately): Get Contents of URL, Method POST, "
        "then Speak Text:\n\n"
        f"{base}/api/wake?token={config.token}"
    )


US_ZONES = {"eastern": "America/New_York", "central": "America/Chicago", "mountain": "America/Denver",
            "arizona": "America/Phoenix", "pacific": "America/Los_Angeles", "alaska": "America/Anchorage",
            "hawaii": "Pacific/Honolulu", "et": "America/New_York", "ct": "America/Chicago",
            "mt": "America/Denver", "pt": "America/Los_Angeles", "est": "America/New_York",
            "cst": "America/Chicago", "mst": "America/Denver", "pst": "America/Los_Angeles"}


def set_timezone(arg: str = "") -> str:
    from datetime import datetime

    from .config import apply_timezone

    if not arg:
        return (f"Current time zone: {os.environ.get('TZ') or 'server default (UTC)'}, "
                f"local time {datetime.now():%I:%M %p}.\nSet it with e.g. /timezone eastern, "
                "/timezone pacific, or /timezone Europe/London")
    name = US_ZONES.get(arg.lower().strip(), arg.strip())
    if not apply_timezone(name):
        return f"I don't know the time zone '{arg}'. Try eastern, central, mountain, pacific, or e.g. America/New_York."
    env = ROOT / ".env"
    lines = [l for l in (env.read_text().splitlines() if env.exists() else []) if not l.startswith("JARVIS_TIMEZONE=")]
    env.write_text("\n".join(lines + [f"JARVIS_TIMEZONE={name}"]) + "\n")
    _restart_soon()
    return f"Time zone set to {name} (it's {datetime.now():%I:%M %p} there). Restarting to apply it everywhere."


FUNNEL_PORT = 8443   # Funnel only on this port and only for /notify; the main Jarvis stays private


def notify_setup(config) -> str:
    """Expose ONLY the notify endpoint publicly (Tailscale Funnel, free), so Claude Code sessions
    anywhere can tell Jarvis they're done."""
    import json
    import re

    tailscale = shutil.which("tailscale")
    if not tailscale:
        return "Tailscale isn't installed on this server."
    code, out = _run(["sudo", "-n", "timeout", "40", tailscale, "funnel", "--bg", f"--https={FUNNEL_PORT}",
                      "--set-path=/notify", f"http://127.0.0.1:{config.port}/api/notify"], timeout=60)
    link = re.search(r"https://login\.tailscale\.com/\S+", out)
    if link:
        return (f"Tailscale needs you to allow Funnel once. Open this, approve, then send /notifysetup again:\n"
                f"{link.group(0)}")
    if code != 0:
        return f"Setting up the public notify link failed:\n{out[-600:]}"
    _, st = _run([tailscale, "status", "--json"], timeout=15)
    try:
        host = json.loads(st)["Self"]["DNSName"].rstrip(".")
    except (ValueError, KeyError):
        host = "<your-server>.ts.net"
    url = f"https://{host}:{FUNNEL_PORT}/notify?token={config.notify_token}"
    return (
        "Public notify link is live (it can only send 'Claude Code is done' pings; nothing else is public):\n\n"
        f"{url}\n\n"
        "Next: give this link to your Claude Code sessions as the environment variable JARVIS_NOTIFY_URL "
        "(I'll walk you through it), then say 'let me know when Claude Code is done'."
    )


def set_env_value(key: str, value: str) -> None:
    env = ROOT / ".env"
    lines = [l for l in (env.read_text().splitlines() if env.exists() else []) if not l.startswith(key + "=")]
    env.write_text("\n".join(lines + [f"{key}={value}"]) + "\n")
    os.environ[key] = value


def set_city(arg: str = "") -> str:
    if not arg:
        return f"Current city: {os.getenv('JARVIS_CITY') or 'not set'}. Set it with /city Dallas"
    set_env_value("JARVIS_CITY", arg.strip())
    return f"Got it. Your morning briefing will include the weather for {arg.strip()}."


def commands(config, jobs, brain=None) -> dict:
    return {
        "status": lambda: status(config, jobs, brain),
        "update": update,
        "restart": lambda: (_restart_soon(), "Restarting; back in about 10 seconds.")[1],
        "logs": logs,
        "shortcut": lambda: shortcut(config),
        "timezone": set_timezone,
        "city": set_city,
        "backup": lambda: __import__("jarvis.backup", fromlist=["x"]).backup_now(config),
        "restore": lambda: __import__("jarvis.backup", fromlist=["x"]).restore(config),
        "notifysetup": lambda: notify_setup(config),
        "github": lambda arg="": __import__("jarvis.github", fromlist=["x"]).save_token(arg, ROOT / ".env")
                  if arg else "Send it like this: /github github_pat_... (see docs/GITHUB.md for how to make one).",
        "textsetup": lambda arg="": __import__("jarvis.sms", fromlist=["x"]).setup(arg, ROOT / ".env"),
        "texttest": lambda: (lambda sms: (sms.send("This is a test. Say hi back, sir.") or "Test text sent.")
                             if sms.configured() else "Spoken texts aren't set up; use /textsetup.")(
                                 __import__("jarvis.sms", fromlist=["x"])),
        "textalt": lambda: __import__("jarvis.sms", fromlist=["x"]).switch_gateway(ROOT / ".env"),
        "textoff": lambda: __import__("jarvis.sms", fromlist=["x"]).disable(ROOT / ".env"),
        "help": lambda: __doc__.strip(),
    }
