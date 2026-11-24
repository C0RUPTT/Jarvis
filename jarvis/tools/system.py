"""Computer control: apps, websites, shell commands, system status, screen, clipboard."""

from __future__ import annotations

import base64
import io
import os
import platform
import shutil
import subprocess
import webbrowser

from . import tool

SYSTEM = platform.system()  # "Windows", "Darwin" (macOS) or "Linux"


@tool(
    "open_application",
    "Open (launch) an application on the user's computer by name, e.g. 'Spotify', "
    "'Visual Studio Code', 'calculator', 'notepad', 'Safari'.",
    {"name": {"type": "string", "description": "Application name"}},
    ["name"],
)
def open_application(ctx, name: str):
    if SYSTEM == "Darwin":
        subprocess.run(["open", "-a", name], check=True, capture_output=True)
    elif SYSTEM == "Windows":
        # ShellExecute resolves names registered with Windows (e.g. notepad, spotify, chrome)
        os.startfile(name)  # type: ignore[attr-defined]  # Windows-only
    else:
        exe = shutil.which(name) or shutil.which(name.lower().replace(" ", "-"))
        if exe:
            subprocess.Popen([exe], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.run(["gtk-launch", name.lower()], check=True, capture_output=True)
    return f"Opened {name}."


@tool(
    "open_url",
    "Open a URL in the user's default web browser. Use for showing websites, "
    "videos (YouTube search URLs work), maps, or search results to the user.",
    {"url": {"type": "string"}},
    ["url"],
)
def open_url(ctx, url: str):
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    webbrowser.open(url)
    return f"Opened {url}."


@tool(
    "run_command",
    "Run a shell command on the user's computer and return its output. Very powerful: "
    "use it for anything without a dedicated tool (volume, media keys, git, file "
    f"management, installing things, querying the system). The OS is {SYSTEM}. "
    "The user is asked to confirm before it runs.",
    {
        "command": {"type": "string", "description": "The command line to execute"},
        "timeout_seconds": {"type": "integer", "description": "Default 60"},
    },
    ["command"],
    dangerous=True,
)
def run_command(ctx, command: str, timeout_seconds: int = 60):
    shell = ["powershell", "-NoProfile", "-Command", command] if SYSTEM == "Windows" else command
    proc = subprocess.run(
        shell, shell=SYSTEM != "Windows", capture_output=True, text=True,
        timeout=timeout_seconds, cwd=os.path.expanduser("~"),
    )
    out = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
    out = out.strip() or "(no output)"
    if len(out) > 20_000:
        out = out[:20_000] + "\n...[truncated]"
    return f"exit code {proc.returncode}\n{out}"


@tool(
    "system_status",
    "Get the computer's status: CPU, memory, disk, battery, uptime, OS.",
)
def system_status(ctx):
    info = {"os": f"{platform.system()} {platform.release()}", "machine": platform.machine()}
    try:
        import psutil
        import time

        info["cpu_percent"] = psutil.cpu_percent(interval=0.5)
        vm = psutil.virtual_memory()
        info["memory"] = f"{vm.percent}% used of {vm.total / 1e9:.1f} GB"
        du = psutil.disk_usage(os.path.expanduser("~"))
        info["disk"] = f"{du.percent}% used, {du.free / 1e9:.0f} GB free"
        batt = psutil.sensors_battery()
        if batt:
            info["battery"] = f"{batt.percent:.0f}% ({'charging' if batt.power_plugged else 'on battery'})"
        info["uptime_hours"] = round((time.time() - psutil.boot_time()) / 3600, 1)
    except ImportError:
        info["note"] = "Install psutil for CPU/memory/battery details."
    return "\n".join(f"{k}: {v}" for k, v in info.items())


@tool(
    "look_at_screen",
    "Take a screenshot of the user's screen so you can see what they are looking at. "
    "Use when the user says things like 'what's on my screen', 'read this', 'help me with this'.",
)
def look_at_screen(ctx):
    import mss
    from PIL import Image

    with mss.mss() as sct:
        shot = sct.grab(sct.monitors[1])  # primary monitor
        img = Image.frombytes("RGB", shot.size, shot.rgb)
    img.thumbnail((1568, 1568))  # keep the image a sensible size for the API
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    data = base64.standard_b64encode(buf.getvalue()).decode()
    return [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}},
        {"type": "text", "text": "Screenshot of the user's primary monitor."},
    ]


@tool("read_clipboard", "Read the text currently on the user's clipboard.")
def read_clipboard(ctx):
    import pyperclip

    return pyperclip.paste() or "(clipboard is empty)"


@tool(
    "write_clipboard",
    "Copy text to the user's clipboard so they can paste it.",
    {"text": {"type": "string"}},
    ["text"],
)
def write_clipboard(ctx, text: str):
    import pyperclip

    pyperclip.copy(text)
    return "Copied to clipboard."
