"""Spoken alerts via text message, so the iPhone can read Jarvis out loud even while unlocked.

Jarvis emails your carrier's free email-to-text address (Verizon: <number>@vtext.com) from a Gmail
account, so it arrives as a normal text. An iPhone Shortcuts automation ("When I get a message
containing 'Jarvis:' -> Speak Text") then speaks it, locked or unlocked.

Caveat: Verizon is retiring email-to-text (by March 31, 2027) and delivery can be unreliable, so
this is a bonus channel; Telegram stays the main one. Set it up with /textsetup in Telegram.
"""

from __future__ import annotations

import os
import re
import smtplib
import ssl
import threading
from email.message import EmailMessage
from pathlib import Path

CARRIER_GATEWAYS = {"verizon": "vtext.com", "verizon-mms": "vzwpix.com"}
PREFIX = "Jarvis: "


def configured() -> bool:
    return all(os.getenv(k) for k in ("JARVIS_SMS_TO", "JARVIS_SMTP_USER", "JARVIS_SMTP_PASSWORD"))


def send(text: str) -> str:
    """Send one text. Returns "" on success, or the error message."""
    to, user = os.getenv("JARVIS_SMS_TO", ""), os.getenv("JARVIS_SMTP_USER", "")
    password = os.getenv("JARVIS_SMTP_PASSWORD", "").replace(" ", "")
    host = os.getenv("JARVIS_SMTP_HOST", "smtp.gmail.com")
    if not (to and user and password):
        return "not set up"
    body = PREFIX + re.sub(r"\s+", " ", text).strip()
    if len(body) > 300:                       # long texts get split or dropped by the gateway
        body = body[:297] + "..."
    msg = EmailMessage()
    msg["From"], msg["To"] = user, to
    msg.set_content(body)                     # no subject: it would be prepended to the text
    try:
        with smtplib.SMTP(host, 587, timeout=20) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(user, password)
            smtp.send_message(msg)
        return ""
    except (smtplib.SMTPException, OSError) as e:
        return str(e)


def send_async(text: str) -> None:
    if configured():
        threading.Thread(target=send, args=(text,), daemon=True).start()


def setup(arg: str, env_file: Path) -> str:
    """/textsetup <10-digit number> <gmail address> <gmail app password>"""
    parts = arg.split()
    at = next((i for i, p in enumerate(parts) if "@" in p), -1)
    if at < 1 or at == len(parts) - 1:
        return ("Send it like this (your message is deleted right after):\n"
                "/textsetup 5551234567 you@gmail.com abcd efgh ijkl mnop\n"
                "The last part is a Gmail app password (see docs/SPOKEN_TEXTS.md).")
    number = re.sub(r"\D", "", "".join(parts[:at]))[-10:]   # "(555) 123-4567" etc.
    if len(number) != 10:
        return "That phone number doesn't look right; use the 10-digit number."
    values = {
        "JARVIS_SMS_TO": f"{number}@{CARRIER_GATEWAYS['verizon']}",
        "JARVIS_SMTP_USER": parts[at],
        "JARVIS_SMTP_PASSWORD": "".join(parts[at + 1:]),
    }
    os.environ.update(values)
    error = send("Test text. If this arrived, set up the speaking automation from docs/SPOKEN_TEXTS.md.")
    if error:
        for k in values:
            os.environ.pop(k, None)
        return f"Sending the test text failed: {error}\nCheck the Gmail address and app password."
    lines = [l for l in (env_file.read_text().splitlines() if env_file.exists() else [])
             if not any(l.startswith(k + "=") for k in values)]
    env_file.write_text("\n".join(lines + [f"{k}={v}" for k, v in values.items()]) + "\n")
    return ("Test text sent to your phone. It can take a minute through Verizon. If it arrives, set up "
            "the speaking automation (docs/SPOKEN_TEXTS.md). If nothing arrives within 5 minutes, "
            "Verizon may be blocking it; send /textoff and we'll stick with Telegram.")


def switch_gateway(env_file: Path) -> str:
    """/textalt: try Verizon's picture-message gateway (vzwpix.com) instead of vtext.com."""
    to = os.getenv("JARVIS_SMS_TO", "")
    if "@" not in to:
        return "Spoken texts aren't set up yet; use /textsetup first."
    number, domain = to.split("@", 1)
    new_domain = "vzwpix.com" if domain == "vtext.com" else "vtext.com"
    os.environ["JARVIS_SMS_TO"] = f"{number}@{new_domain}"
    error = send(f"Test via {new_domain}. If this arrived, set up the speaking automation.")
    if error:
        os.environ["JARVIS_SMS_TO"] = to
        return f"Sending through {new_domain} failed: {error}"
    lines = [l for l in env_file.read_text().splitlines() if not l.startswith("JARVIS_SMS_TO=")]
    env_file.write_text("\n".join(lines + [f"JARVIS_SMS_TO={number}@{new_domain}"]) + "\n")
    return (f"Switched to {new_domain} and sent a test text. Give it a few minutes. If this one doesn't "
            "arrive either, Verizon is blocking email-to-text for us; send /textoff.")


def disable(env_file: Path) -> str:
    keys = ("JARVIS_SMS_TO", "JARVIS_SMTP_USER", "JARVIS_SMTP_PASSWORD")
    for k in keys:
        os.environ.pop(k, None)
    if env_file.exists():
        env_file.write_text("\n".join(l for l in env_file.read_text().splitlines()
                                      if not any(l.startswith(k + "=") for k in keys)) + "\n")
    return "Spoken texts turned off. Telegram stays as it is."
