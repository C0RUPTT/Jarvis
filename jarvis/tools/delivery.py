"""Controlling how and when Jarvis interrupts: normal, quiet (silent notifications) and hold
(keep everything until the user asks what they missed)."""

from __future__ import annotations

from . import tool


def _announcer(ctx):
    announcer = ctx.extras.get("announcer")
    if announcer is None:
        raise RuntimeError("Notifications aren't available in this mode.")
    return announcer


@tool(
    "set_delivery_mode",
    "Change how Jarvis delivers things it says on its own (finished jobs, timers, reminders). "
    "'normal': notify with sound. 'quiet': silent notifications (user is busy, in a meeting, "
    "'tell me quietly'). 'hold': send nothing and keep everything until the user asks what they "
    "missed ('hold everything', 'don't bother me'). Urgent items always get through.",
    {"mode": {"type": "string", "enum": ["normal", "quiet", "hold"]}},
    ["mode"],
)
def set_delivery_mode(ctx, mode: str):
    return _announcer(ctx).set_mode(mode)


@tool(
    "what_did_i_miss",
    "Get everything that was held back while the user was away or in hold mode. Use for "
    "'what did I miss?', 'anything new?', 'catch me up'. Also check job_status for finished work.",
)
def what_did_i_miss(ctx):
    announcer = _announcer(ctx)
    held = announcer.take_held()
    mode_note = f" (Delivery mode is still '{announcer.mode}'.)" if announcer.mode != "normal" else ""
    if not held:
        return "Nothing was held." + mode_note
    return "Held while away:\n" + "\n".join(f"- {h}" for h in held) + mode_note
