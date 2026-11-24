"""Desktop control: mouse and keyboard, so Jarvis can operate any app it can see.

Pair with look_at_screen: Claude looks, then clicks/types using the screenshot's
coordinates. Needs Windows, macOS, or Linux with an X11 session (not Wayland).
"""

from __future__ import annotations

from . import tool
from . import system


def _gui():
    import pyautogui

    pyautogui.FAILSAFE = True  # slam the mouse into a screen corner to abort
    return pyautogui


def _to_screen(x: int, y: int) -> tuple[int, int]:
    scale = system.LAST_SCREENSHOT_SCALE
    return round(x * scale), round(y * scale)


@tool(
    "mouse_click",
    "Click at a position on screen. x/y are pixel coordinates in the most recent "
    "look_at_screen image (call look_at_screen first).",
    {
        "x": {"type": "integer"},
        "y": {"type": "integer"},
        "button": {"type": "string", "enum": ["left", "right", "middle"]},
        "double": {"type": "boolean"},
    },
    ["x", "y"],
)
def mouse_click(ctx, x: int, y: int, button: str = "left", double: bool = False):
    sx, sy = _to_screen(x, y)
    _gui().click(sx, sy, clicks=2 if double else 1, button=button)
    return f"Clicked {button} at screen ({sx}, {sy})."


@tool(
    "type_text",
    "Type text with the keyboard into whatever is focused.",
    {"text": {"type": "string"}},
    ["text"],
)
def type_text(ctx, text: str):
    _gui().write(text, interval=0.01)
    return f"Typed {len(text)} characters."


@tool(
    "press_keys",
    "Press a key or key combination, e.g. 'enter', 'ctrl+c', 'alt+tab', 'ctrl+shift+t', "
    "'volumeup', 'playpause', 'nexttrack'.",
    {"keys": {"type": "string"}},
    ["keys"],
)
def press_keys(ctx, keys: str):
    parts = [k.strip().lower() for k in keys.replace(" ", "").split("+") if k.strip()]
    _gui().hotkey(*parts)
    return f"Pressed {keys}."


@tool(
    "scroll",
    "Scroll the mouse wheel. Positive = up, negative = down (try 5 or -5).",
    {"amount": {"type": "integer"}},
    ["amount"],
)
def scroll(ctx, amount: int):
    import platform

    # Windows counts wheel movement in 1/120ths of a notch; other systems count notches.
    _gui().scroll(amount * 120 if platform.system() == "Windows" else amount)
    return f"Scrolled {amount}."
